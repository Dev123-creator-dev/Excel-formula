import pandas as pd
import streamlit as st
import oracledb

"""
Helper function to query BioMAP Oracle database in nonprod using existing service account
"""

# Database Configuration

DB_USER     =       st.secrets["database"]["username"]
DB_PASS     =       st.secrets["database"]["password"]
DB_HOST     =       st.secrets["database"]["host"]
DB_PORT     =       st.secrets["database"]["port"]
DB_SERVICE  =       st.secrets["database"]["db_service"]


# Data loading functions
def query_view(query: str,) -> pd.DataFrame:

  """
  Connects to Oracle database using the service account, queries VW_TRUSTED_PROFILES, and returns Pandas dataframe.
  """

  try:

    # Establish connection with BioMAP Oracle Database
    connection = oracledb.connect(
      user=DB_USER,
      password=DB_PASS,
      host=DB_HOST,
      port=DB_PORT,
      sid=DB_SERVICE
    )

    # Create cursor and execute query
    cursor = connection.cursor()
    cursor.execute(query)

    # Fetch column names and data
    columns = [col[0] for col in cursor.description]
    data = cursor.fetchall()

    # Load directly into dataframe
    df = pd.DataFrame(data, columns=columns)

    # End connections
    cursor.close()
    connection.close()

    return df

  except oracledb.Error as e:
    print(f"BioMAP Oracle Database connection or query failed: {e}")

  except Exception as e:
    print(f"An unexpected error occurred: {e}")

def query_trusted_filtered_combined():

  """
  Query for View supplying data to TrustedFilteredCombined Profile type in Viewer.
  """

  db_df = query_view(f"SELECT * FROM reload.VW_TRUSTED_FILTERED_PROFILES")

  return db_df

def query_dmso_controls():

  """
  Query for View that combines DMSO control data from HTS legacy database MV_DMSO_CTRL and Uploader view VW_DMSO_CTRL.
  """

  ctrl_df = query_view(f"SELECT * FROM reload.DMSO_CTRL")

  return ctrl_df
