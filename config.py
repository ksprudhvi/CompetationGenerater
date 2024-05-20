import os

settings = {
    'host': os.environ.get('ACCOUNT_HOST', 'https://scorecardgendata.documents.azure.com:443/'),
    'master_key': os.environ.get('ACCOUNT_KEY', 'rJPINxAmYWh9j7ryJMyC9VjeCcSA9VGq2rOo49YM6r3suh3N1fQ38KoKIsNlIwS5bqVjERQtYpI3ACDb8WpECw=='),
    'competitionDB': os.environ.get('COSMOS_DATABASE', 'EventCreator'),
    'container1': os.environ.get('COSMOS_CONTAINER', 'EventMeta')
}
