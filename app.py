import uuid
from datetime import datetime, timedelta

from flask import Flask, request, jsonify
from azure.cosmos import CosmosClient, exceptions
import config
from flask_cors import CORS
import string
import random
import azure.cosmos.exceptions as exceptions
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient, generate_blob_sas, BlobSasPermissions

app = Flask(__name__)
cors = CORS(app)
# Define Azure Cosmos DB connection settings
# Replace these placeholders with your actual Cosmos DB details
COSMOS_ENDPOINT = config.settings['host']
COSMOS_KEY = config.settings['master_key']
DATABASE_NAME = config.settings['competitionDB']

# Initialize Cosmos DB client
client = CosmosClient(COSMOS_ENDPOINT, credential=COSMOS_KEY)
database = client.get_database_client(DATABASE_NAME)

BlobConnection_string = "DefaultEndpointsProtocol=https;AccountName=scorecardgen;AccountKey=09fO4n7Nko8mjcAamRJzbXgbJBZAxmXC5/pkjn+m+0n1grVbnQVGMOh9kUMi1Oth4spfo2bZCD3l+AStpCbUgA==;EndpointSuffix=core.windows.net"
BlobContainer_name = "titleimages"

# Create a BlobServiceClient object
blob_service_client = BlobServiceClient.from_connection_string(BlobConnection_string)
container_client = blob_service_client.get_container_client(BlobContainer_name)

# Function to upload image to Azure Blob Storage
def upload_image(file):
    try:
        blob_client = container_client.get_blob_client(file.filename)
        blob_client.upload_blob(file)
        expiry_time = datetime.utcnow() + timedelta(days=365*100)
        sas_token = generate_blob_sas(
            account_name=blob_service_client.account_name,
            container_name=BlobContainer_name,
            blob_name=file.filename,
            account_key=blob_service_client.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=expiry_time
        )
        # Construct the URL with SAS token
        blob_url = f"https://{blob_service_client.account_name}.blob.core.windows.net/{BlobContainer_name}/{file.filename}?{sas_token}"
        return jsonify({'ImageUrl':blob_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Function to retrieve image from Azure Blob Storage
def get_image(filename):
    blob_client = container_client.get_blob_client(filename)
    blob_data = blob_client.download_blob()
    return blob_data.readall()

@app.route('/upload', methods=['POST'])
def upload():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'})
        file = request.files['file']
        file.filename=request.form['EventId']
        if file.filename == '':
            return jsonify({'error': 'No selected file'})
        ImageUrl=upload_image(file)
        return ImageUrl
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/image/<filename>', methods=['GET'])
def get_image_route(filename):
    image_data = get_image(filename)
    return image_data, 200, {'Content-Type': 'image/jpeg'}

def generate_unique_id():
    return str(uuid.uuid4())
# Write data to Azure Cosmos DB
@app.route('/competition', methods=['POST'])
def create_competition():
    data = request.json
    data["id"]=generate_unique_id()

    container = database.get_container_client("EventMeta")
    try:
        container.create_item(body=data)
        return jsonify({"eventId": data["EventId"]}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/updateTeams', methods=['POST'])
def createTeams():
    data = request.json
    data["id"]=generate_unique_id()
    container = database.get_container_client("EventTeamsJudges")
    try:
        container.create_item(body=data)
        generateAccessTokensCoachAccess(data)
        return jsonify({"eventId": data["EventId"]}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/getTeamsJudges/<EventId>', methods=['GET'])
def getTeamsJudges(EventId):
    try:
        container = database.get_container_client("EventTeamsJudges")
        query = "SELECT * FROM c WHERE c.EventId = @EventId"
        # Define the parameters for the query
        query_params = [
            {"name": "@EventId", "value": EventId}
        ]
        # Execute the query
        items = list(container.query_items(
            query=query,
            parameters=query_params,
            enable_cross_partition_query=True
        ))
        return jsonify(items), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def generate_token():
    """Generates a unique 6-character alphanumeric token."""
    alphanumeric = string.ascii_letters + string.digits
    token = ''.join(random.sample(alphanumeric, 6))
    return token
def generateAccessTokensJudges(data):
    accessTokenContainer = database.get_container_client("EventAccessTokens")
    for judge in data.get('JudegsInfo', []):
        judge_id = judge.get('id')
        judge_name = judge.get('name')
        scorecardAccessTokens = {
            'id':generate_unique_id(),
            'EventId':data["EventId"],
            'judgeId': judge_id,
            'judgeName':judge_name,
            'HostAccess':False,
            'JudgeAccess':True,
            'CoachAccess':False,
            'TokenId':generate_token()
        }
        try:
            # Insert scorecard document into container
            accessTokenContainer.create_item(body=scorecardAccessTokens)
        except Exception as e:
            return jsonify({"error": str(e)}), 500


def generateAccessTokensCoachAccess(data):
    accessTokenContainer = database.get_container_client("EventAccessTokens")
    for coachData in data.get('teamsInfo', []):
        coach=coachData['coachName']
        coach_id = coach.get('id')
        coach_name = coach.get('name')
        scorecardAccessTokens = {
            'id':generate_unique_id(),
            'EventId':data["EventId"],
            'coachId': coach_id,
            'coachName':coach_name,
            'CoachEmail':coach.get('email'),
            'HostAccess':False,
            'JudgeAccess':False,
            'CoachAccess':True,
            'TokenId':generate_token()
        }
        try:
            # Insert scorecard document into container
            accessTokenContainer.create_item(body=scorecardAccessTokens)
        except Exception as e:
            return jsonify({"error": str(e)}), 500


def generateAccessTokensHostAccess(data):
    accessTokenContainer = database.get_container_client("EventScoreCard")
    scorecardAccessTokens = {
        'id':generate_unique_id(),
        'HostEmail':data['HostEmail'],
        'HostAccess':True,
        'JudgeAccess':True,
        'CoachAccess':True,
    }
    try:
        # Insert scorecard document into container
        accessTokenContainer.create_item(body=scorecardAccessTokens)
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route('/updateJudges', methods=['POST'])
def createJudges():
    data = request.json
    container = database.get_container_client("EventTeamsJudges")
    query = "SELECT * FROM c WHERE c.EventId = @EventId"
    # Define the parameters for the query
    query_params = [
        {"name": "@EventId", "value": data["EventId"]}
    ]
    # Execute the query
    items = list(container.query_items(
        query=query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))
    dataTemp=items[0]
    try:
        dataTemp['JudegsInfo']=data['JudegsInfo']
        updated_document = container.replace_item(item=dataTemp['id'], body=dataTemp)
        generateAccessTokensJudges(updated_document)
        add_scorecard(dataTemp)
        return jsonify(updated_document), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/Updatecompetition', methods=['POST'])
def update_competition():
    data = request.json
    container = database.get_container_client("EventMeta")
    try:
        # Replace the existing competition data with the updated one
        updated_document = container.replace_item(item=data["id"], body=data)
        return jsonify({"message": "Competition data updated successfully", "updated_data": updated_document}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Fetch data from Azure Cosmos DB based on CompetitionId
@app.route('/getEvent/', methods=['POST'])
def get_competition():
    try:
        data = request.json
        container = database.get_container_client("EventMeta")
        competition_id=data["EventId"]
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
        items = container.query_items(query=query, enable_cross_partition_query=True)
        results = list(items)
        results=results[0]
        return jsonify(results), 200
    except exceptions.CosmosResourceNotFoundError:
        return jsonify({"error": "Competition not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/allcompe', methods=['GET'])
def getAllcompetition():
    try:
        container = database.get_container_client("EventMeta")
        query = "SELECT * FROM c"
        items = container.query_items(query=query, enable_cross_partition_query=True)
        results = list(items)
        return jsonify(results), 200
    except exceptions.CosmosResourceNotFoundError:
        return jsonify({"error": "Competition not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route("/")
def hello():
    return "hello Server is up"
# Delete competition from Azure Cosmos DB based on CompetitionId
@app.route('/competition/', methods=['DELETE'])
def delete_competition():
    try:
        data = request.json
        container = database.get_container_client("EventMeta")
        container.delete_item(item=data["id"], partition_key=data["EventId"])
        return jsonify({"message": "Competition deleted successfully"}), 200
    except exceptions.CosmosResourceNotFoundError:
        return jsonify({"error": "Competition not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
def add_scorecard(data):
    competition_id = data.get('EventId')
    # Initialize Cosmos Client
    scorecard_container = database.get_container_client("EventScoreCard")
    # Create scorecard entry for every judge * team combination
    for judge in data.get('JudegsInfo', []):
        judge_id = judge.get('id')
        judge_name = judge.get('name')
        for team in data.get('teamsInfo', []):
            team_id = team.get('teamName', {}).get('id')
            team_name = team.get('teamName', {}).get('name')
            # Create initial scorecard document
            scorecard_document = {
                'id':generate_unique_id(),
                'EventId':data["EventId"],
                'judgeId': judge_id,
                'judgeName':judge_name,
                'teamId': team_id,
                'teamName':team_name,
                'teamMemberId': None,  # Assuming we don't have specific team member ID here
                'scorecard': {
                    'creativity': 0,
                    'formation': 0,
                    'technique': 0,
                    'difficulty': 0,
                    'sync': 0,
                    'total':0,
                }
            }
            try:
            # Insert scorecard document into container
                scorecard_container.create_item(body=scorecard_document)
            except Exception as e:
                return jsonify({"error": str(e)}), 500
@app.route('/update_scores', methods=['POST'])
def update_scores():
    try:
        data = request.json
        scorecard_id=data["id"]
        eventId=data["EventId"]
        new_scores=data["scorecard"]
        scorecard_container = database.get_container_client("EventScoreCard")
        # Retrieve the scorecard document from the database
        scorecard_document = scorecard_container.read_item(item=scorecard_id,partition_key=eventId)
        # Update the scores in the scorecard document
        scorecard_document['scorecard'].update(new_scores)
        # Replace the existing document with the updated one
        updated_document = scorecard_container.replace_item(item=scorecard_id, body=scorecard_document)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify(updated_document)
@app.route('/getScorecard', methods=['POST'])
def getScorecard():
    try:
        data = request.json
        competition_id = data.get('EventId')
        judge_id = data.get('judgeId')
        teamId = data.get('teamId')
        if not competition_id or not judge_id:
            return jsonify({"error": "Please provide both competitionId and judgeId in the request body"}), 400
        scorecard_container = database.get_container_client("EventScoreCard")
            # Query scorecards for the given competition_id and judge_id
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}' AND c.judgeId = '{judge_id}' AND c.teamId='{teamId}'"
        scorecards = list(scorecard_container.query_items(query=query, enable_cross_partition_query=True))
        return jsonify(scorecards), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route('/validateJudgeAccessToken', methods=['POST'])
def validateJudgeAccessToken():
    try:
        data = request.json
        competition_id = data.get('EventId')
        judge_id = data.get('judgeId')
        tokenValidation = database.get_container_client("EventAccessTokens")
        if not competition_id or not judge_id:
            return jsonify({"error": "Please provide both competitionId and judgeId in the request body"}), 400
        validationQuery = f"SELECT * FROM c WHERE c.EventId = '{competition_id}' AND c.judgeId = '{judge_id}'"
        Tokens = list(tokenValidation.query_items(query=validationQuery, enable_cross_partition_query=True))
        Tokens=Tokens[0]
        if(Tokens['TokenId']==data['TokenId']):
            result={'validation':'true'}
        else:
            result={'validation':'false'}
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/getAccessTokens', methods=['POST'])
def getAccessTokens():
    try:
        data = request.json
        competition_id = data.get('EventId')
        scorecard_container = database.get_container_client("EventAccessTokens")
        # Query scorecards for the given competition_id and judge_id
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
        scorecards = list(scorecard_container.query_items(query=query, enable_cross_partition_query=True))
        return jsonify(scorecards), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route('/getleaderboard', methods=['POST'])
def get_leaderboard():
    try:
        data = request.json
        competition_id=data['EventId']
        scorecard_container = database.get_container_client("EventScoreCard")
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
        scorecards = list(scorecard_container.query_items(query=query, enable_cross_partition_query=True))
        # Calculate total scores for each team
        team_scores = {}
        for scorecard in scorecards:
            team_id = scorecard['teamId']
            team_name=scorecard['teamName']
            score = scorecard['scorecard']['creativity']+scorecard['scorecard']['sync'] + scorecard['scorecard']['formation'] + scorecard['scorecard']['technique'] + scorecard['scorecard']['difficulty']
            team_scores[team_id] = team_scores.get(team_id, 0) + score
        # Sort the teams by total score
        sorted_teams = sorted(team_scores.items(), key=lambda x: x[1], reverse=True)
        leaderboard = [{'teamId': team_id, 'total_score': total_score} for team_id,total_score in sorted_teams]

        return jsonify({"leaderboard": leaderboard}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0")


