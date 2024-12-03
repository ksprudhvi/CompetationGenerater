import os

settings = {
    'host': os.environ.get('ACCOUNT_HOST', 'https://unteventmanagmentdb.documents.azure.com:443/'),
    'master_key': os.environ.get('ACCOUNT_KEY', 'g6Lp3sF2lt9ZYSLiaIqmbXvDFtEgg9UVnPiBYv8hYf7kA5MyWU7hFJYUxgibwspDY7kdDQJ0XlajACDbIBNHAg=='),
    'competitionDB': os.environ.get('COSMOS_DATABASE', 'EventCreator'),
    'container1': os.environ.get('COSMOS_CONTAINER', 'EventMeta')
}