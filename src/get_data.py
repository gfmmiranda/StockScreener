# scripts/download_data.py
import os
import pandas as pd
import yfinance as yf
from sqlalchemy import create_engine, inspect, text
from datetime import datetime
from tqdm import tqdm


def download_stock_prices(tickers, start_years_ago=10):

    """
    Download stock prices from Yahoo Finance.
    
    Args:
        tickers (list): List of stock tickers.
        start_years_ago (int): Number of years ago to start downloading data.
    
    Returns:
        pd.DataFrame: DataFrame with stock prices.

    """
    
    end_date = datetime.today()
    start_date = datetime(end_date.year - start_years_ago, end_date.month, end_date.day)
    
    df = yf.download(tickers, start=start_date, end=end_date, group_by='ticker', progress=True)
    
    # Flatten
    flat_list = []
    for ticker in tickers:
        temp = df[ticker].copy()
        temp['ticker'] = ticker
        temp = temp.reset_index()
        flat_list.append(temp)
    
    all_prices = pd.concat(flat_list)
    return all_prices

# Mapping TICKER X CNPJ
def load_map(file_path):

    """
    Load mapping file and treat multiples Tickers.

    Args:
        file_path (str): Path to the mapping file.

    Returns:
        pd.DataFrame: DataFrame with the mapping of CNPJ to Tickers.

    """

    # Read the mapping file
    mapping = pd.read_csv(file_path, sep = '\t')

    # Check for companies with more than one Ticker
    max_tickers = mapping['TICKER'].str.split('/').str.len().max()
    ticker_cols = [ f'TICKER{i+1}' for i in range(max_tickers) ]

    # Create new columns for each Ticker
    mapping[ticker_cols] = mapping['TICKER'].str.split('/', expand=True)
    mapping = mapping.drop(columns=['TICKER'])

    # Rename columns with SA
    for col in ['TICKER1', 'TICKER2', 'TICKER3']:
        mapping[col] = mapping[col] + '.SA'

    return mapping

# Loading DRE Data
def load_dre(file_path):
    """
    Load DRE data and treat it.
    """

    # Read the DRE file
    dre = pd.read_csv(file_path, sep=';', encoding='latin1')

    # Filter dre
    dre = dre[['CNPJ_CIA', 'DENOM_CIA', 'ESCALA_MOEDA', 'DT_FIM_EXERC', 'CD_CONTA', 'VL_CONTA']]

    dre = dre.loc[
        dre['CD_CONTA'].isin(['3.01', '3.11'])
    ].sort_values(by=['CNPJ_CIA', 'DT_FIM_EXERC'])

    dre.drop_duplicates(subset=['CNPJ_CIA', 'DENOM_CIA', 'ESCALA_MOEDA', 'DT_FIM_EXERC', 'CD_CONTA'], inplace=True)

    # Formatting output
    dre = dre.pivot(
        index=['CNPJ_CIA', 'DENOM_CIA', 'ESCALA_MOEDA', 'DT_FIM_EXERC'], 
        columns=['CD_CONTA'],
        values='VL_CONTA').reset_index().rename(
            columns={
                '3.01': 'RECEITA_LIQUIDA',
                '3.11': 'LUCRO_CONSOLIDADO',
                'CNPJ_CIA': 'CNPJ',
                'DENOM_CIA': 'NOME',
            }
        )

    return dre

# Loading BP Data
def load_bpp(file_path):
    """
    Load BPP data and treat it.
    """

    # Read the DRE file
    bp = pd.read_csv(file_path, sep=';', encoding='latin1')

    # Filter dre
    bp = bp[['CNPJ_CIA', 'DENOM_CIA', 'ESCALA_MOEDA', 'DT_FIM_EXERC', 'ORDEM_EXERC', 'CD_CONTA', 'DS_CONTA', 'VL_CONTA']]

    bp = bp.loc[
        (bp['CD_CONTA'].isin(['2.03'])) & (bp['DS_CONTA'].str.lower().str.contains('patrimônio')) & (bp['ORDEM_EXERC'].str.lower() == 'último')
    ].sort_values(by=['CNPJ_CIA', 'DT_FIM_EXERC'])

    # Drop duplicates
    bp.drop_duplicates(subset=['CNPJ_CIA', 'DENOM_CIA', 'ESCALA_MOEDA', 'DT_FIM_EXERC', 'CD_CONTA'], inplace=True)

    # Aggregate
    bp = bp.groupby(['CNPJ_CIA', 'DENOM_CIA', 'ESCALA_MOEDA', 'DT_FIM_EXERC', 'CD_CONTA'], as_index=False).max()

    # Formatting output
    bp = bp.pivot(
        index=['CNPJ_CIA', 'DENOM_CIA', 'ESCALA_MOEDA', 'DT_FIM_EXERC'], 
        columns=['CD_CONTA'],
        values='VL_CONTA').reset_index().rename(
            columns={
                '2.03': 'PATRIMONIO_LIQUIDO',
                'CNPJ_CIA': 'CNPJ',
                'DENOM_CIA': 'NOME',
            }
        )

    return bp

# Merge DRE and BPP
def combine_financials(mapping, dre, bpp):
    """
    Get financials from mapping and DRE.
    """

    # Merge mapping with DRE
    merged = pd.merge(
        mapping[['CNPJ', 'TICKER1', 'TICKER2', 'TICKER3']],
        dre,
        how='inner',
        left_on='CNPJ',
        right_on='CNPJ'
    )

    # Merge with BPP
    merged = pd.merge(
        merged,
        bpp[['CNPJ', 'PATRIMONIO_LIQUIDO', 'DT_FIM_EXERC']],
        how='inner',
        left_on=['CNPJ', 'DT_FIM_EXERC'],
        right_on=['CNPJ', 'DT_FIM_EXERC']
    )

    return merged.sort_values(by=['NOME', 'DT_FIM_EXERC'])

# Get all financials
def get_all_financials(mapping_file, db_dir, dfp_dir, save_to_db = False):

    """
    Create a SQLite database with financial data from the CVM DFP dataset.

    Parameters
    ----------
        mapping_file : str
            Path to the mapping file.

        DATABASE_DIR : str
            Path to the SQLite database file.
            
        DFP_DIR : str
            Path to the directory containing the DFP files.

    Returns
    -------
        pd.DataFrame
            DataFrame with the financial data.

    """
    
    # Load the map
    mapping = load_map(mapping_file)

    if save_to_db:
        # Create database connection
        engine = create_engine(f"sqlite:///{db_dir}")

        # Drop all tables in the database
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS financials"))

    all_financials = []
    # Process files
    for dir in os.listdir(dfp_dir):

        print(f"Processing {dir}...")

        year = dir[-4:]
        year_dir = os.path.join(dfp_dir, dir)

        # Load dre
        dre_file = os.path.join(year_dir, f"dfp_cia_aberta_DRE_con_{year}.csv")
        dre = load_dre(dre_file)

        # Load bp
        bpp_file = os.path.join(year_dir, f"dfp_cia_aberta_BPP_con_{year}.csv")
        bpp = load_bpp(bpp_file)

        # Merge
        financials_df = combine_financials(mapping, dre, bpp)

        # Save to database
        if save_to_db:
            financials_df.to_sql('financials', engine, if_exists='append', index=False)

        # Append to list
        all_financials.append(financials_df)
    
    # Concatenate all financials
    all_financials = pd.concat(all_financials, ignore_index=True)

    return all_financials


def drop_all_tables(engine):
    """
    Drop all tables in the database.

    Args:
        engine (sqlalchemy.engine.Engine): SQLAlchemy engine object.
        
    """

    inspector = inspect(engine)
    with engine.begin() as conn:
        for table_name in inspector.get_table_names():
            conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
            print(f"Dropped table {table_name}")
