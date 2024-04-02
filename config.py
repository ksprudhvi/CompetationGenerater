import os

settings = {
    'host': os.environ.get('ACCOUNT_HOST', 'https://scorecardgendb.documents.azure.com:443/'),
    'master_key': os.environ.get('ACCOUNT_KEY', 'FTUQgUomTG2bQwnva0OdHfLRxeUdBOvM9tGzOBtMciWYPyZsDsfW3mWLYU94KmlChAUNwxcRuj0MACDbfkyYcg=='),
    'database_id': os.environ.get('COSMOS_DATABASE', 'competition'),
    'container_id': os.environ.get('COSMOS_CONTAINER', 'Container2'),
}