import uuid

from flask import Flask, request, jsonify
from azure.cosmos import CosmosClient, exceptions
import config
from flask_cors import CORS
import azure.cosmos.documents as documents
import azure.cosmos.cosmos_client as cosmos_client
import azure.cosmos.exceptions as exceptions
from azure.cosmos.partition_key import PartitionKey
import datetime
CORS(app)
app = Flask(__name__)

# Define Azure Cosmos DB connection settings
# Replace these placeholders with your actual Cosmos DB details
COSMOS_ENDPOINT = config.settings['host']
COSMOS_KEY = config.settings['master_key']
DATABASE_NAME = config.settings['competitionDB']

# Initialize Cosmos DB client
client = CosmosClient(COSMOS_ENDPOINT, credential=COSMOS_KEY)
database = client.get_database_client(DATABASE_NAME)

def generate_unique_id():
    return str(uuid.uuid4())
# Write data to Azure Cosmos DB
@app.route('/competition', methods=['POST'])
def create_competition():
    data = request.json
    data["id"]=generate_unique_id()
    container = database.get_container_client("CompetitionsData")
    for judge in data.get('judges', []):
        judge['id'] = generate_unique_id()
    venueLocation = data.get('venueLocation')
    venueLocation['id'] = generate_unique_id()
    for team in data.get('teams', []):
        team['coachName']['id'] = generate_unique_id()
        for member in team['teamMembers']:
            member['id'] = generate_unique_id()
        team['teamName']['id'] = generate_unique_id()
    try:
        container.create_item(body=data)
        add_scorecard(data)
        return jsonify({"message": "Competition created successfully"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route('/Updatecompetition', methods=['POST'])
def update_competition():
    data = request.json
    container = database.get_container_client("CompetitionsData")
    try:
        # Replace the existing competition data with the updated one
        updated_document = container.replace_item(item=data["id"], body=data)
        return jsonify({"message": "Competition data updated successfully", "updated_data": updated_document}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Fetch data from Azure Cosmos DB based on CompetitionId
@app.route('/competition/<competition_id>', methods=['GET'])
def get_competition(competition_id):
    try:
        container = database.get_container_client("CompetitionsData")
        item = container.read_item(item=competition_id, partition_key=competition_id)
        return jsonify(item), 200
    except exceptions.CosmosResourceNotFoundError:
        return jsonify({"error": "Competition not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/allcompe', methods=['GET'])
def getAllcompetition():
    try:
        container = database.get_container_client("CompetitionsData")
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
@app.route('/competition/<competition_id>', methods=['DELETE'])
def delete_competition(competition_id):
    try:
        container = database.get_container_client("CompetitionsData")
        container.delete_item(item=competition_id, partition_key=competition_id)
        return jsonify({"message": "Competition deleted successfully"}), 200
    except exceptions.CosmosResourceNotFoundError:
        return jsonify({"error": "Competition not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
def add_scorecard(data):
    data = request.json
    competition_id = data.get('id')
    # Initialize Cosmos Client
    scorecard_container = database.get_container_client("ScoreCardData")
    # Create scorecard entry for every judge * team combination
    for judge in data.get('judges', []):
        judge_id = judge.get('id')
        judge_name = judge.get('name')
        for team in data.get('teams', []):
            team_id = team.get('teamName', {}).get('id')
            team_name = team.get('teamName', {}).get('name')
            # Create initial scorecard document
            scorecard_document = {
                'id':generate_unique_id(),
                'competitionId': competition_id,
                'judgeId': judge_id,
                'judgeName':judge_name,
                'teamId': team_id,
                'teamName':team_name,
                'teamMemberId': None,  # Assuming we don't have specific team member ID here
                'scorecard': {
                    'creativity': 0,
                    'presentation': 0,
                    'innovation': 0,
                    'teamwork': 0
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
        new_scores=data["scorecard"]
        scorecard_container = database.get_container_client("ScoreCardData")
        # Retrieve the scorecard document from the database
        scorecard_document = scorecard_container.read_item(item=scorecard_id,partition_key=scorecard_id)
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
        competition_id = data.get('competitionId')
        judge_id = data.get('judgeId')
        if not competition_id or not judge_id:
            return jsonify({"error": "Please provide both competitionId and judgeId in the request body"}), 400
        scorecard_container = database.get_container_client("ScoreCardData")
        # Query scorecards for the given competition_id and judge_id
        query = f"SELECT * FROM c WHERE c.competitionId = '{competition_id}' AND c.judgeId = '{judge_id}'"
        scorecards = list(scorecard_container.query_items(query=query, enable_cross_partition_query=True))
        return jsonify(scorecards), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route('/getleaderboard', methods=['POST'])
def get_leaderboard():
    try:
        data = request.json
        competition_id=data['id']
        scorecard_container = database.get_container_client("ScoreCardData")
        query = f"SELECT * FROM c WHERE c.competitionId = '{competition_id}'"
        scorecards = list(scorecard_container.query_items(query=query, enable_cross_partition_query=True))

        # Calculate total scores for each team
        team_scores = {}
        for scorecard in scorecards:
            team_id = scorecard['teamId']
            score = scorecard['scorecard']['creativity'] + scorecard['scorecard']['presentation'] + scorecard['scorecard']['innovation'] + scorecard['scorecard']['teamwork']
            team_scores[team_id] = team_scores.get(team_id, 0) + score

        # Sort the teams by total score
        sorted_teams = sorted(team_scores.items(), key=lambda x: x[1], reverse=True)
        leaderboard = [{'teamId': team_id, 'total_score': total_score} for team_id, total_score in sorted_teams]

        return jsonify({"leaderboard": leaderboard}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0")
    

