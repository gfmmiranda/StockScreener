import pandas as pd
from sqlalchemy import create_engine

def screen_stocks(pe_threshold=15, roe_threshold=10, db_path='data/stock_data.db'):
    engine = create_engine(f'sqlite:///{db_path}')
    
    # Load financials
    query = "SELECT * FROM financials"
    financials_df = pd.read_sql(query, engine)
    
    # Apply filters
    screened = financials_df[
        (financials_df['P/E'] < pe_threshold) &
        (financials_df['ROE'] > roe_threshold)
    ]
    
    # Sort
    screened = screened.sort_values(by='ROE', ascending=False)
    
    return screened

if __name__ == "__main__":
    top_stocks = screen_stocks()
    print("✅ Top Stocks after screening:")
    print(top_stocks)
