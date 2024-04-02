import os

settings = {
    'host': os.environ.get('ACCOUNT_HOST', 'https://scorecardgendb.documents.azure.com:443/'),
    'master_key': os.environ.get('ACCOUNT_KEY', 'FTUQgUomTG2bQwnva0OdHfLRxeUdBOvM9tGzOBtMciWYPyZsDsfW3mWLYU94KmlChAUNwxcRuj0MACDbfkyYcg=='),
    'competitionDB': os.environ.get('COSMOS_DATABASE', 'competition'),
    'container1': os.environ.get('COSMOS_CONTAINER', 'Container2'),
}
