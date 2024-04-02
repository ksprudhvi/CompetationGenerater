from flask import Flask, request, jsonify
from azure.cosmos import CosmosClient, exceptions
import config
import azure.cosmos.documents as documents
import azure.cosmos.cosmos_client as cosmos_client
import azure.cosmos.exceptions as exceptions
from azure.cosmos.partition_key import PartitionKey
import datetime

app = Flask(__name__)

# Define Azure Cosmos DB connection settings
# Replace these placeholders with your actual Cosmos DB details
COSMOS_ENDPOINT = config.settings['host']
COSMOS_KEY = config.settings['master_key']
DATABASE_NAME = config.settings['database_id']
CONTAINER_NAME = config.settings['container_id']

# Initialize Cosmos DB client
client = CosmosClient(COSMOS_ENDPOINT, credential=COSMOS_KEY)
database = client.get_database_client(DATABASE_NAME)
container = database.get_container_client(CONTAINER_NAME)

# Write data to Azure Cosmos DB
@app.route('/competition', methods=['POST'])
def create_competition():
    data = request.json
    query = "SELECT TOP 1 VALUE MAX(c.id) FROM c"
    result_iterable = container.query_items(query=query, enable_cross_partition_query=True)
    max_id = list(result_iterable)[0]
    data["id"]=str(int(max_id)+1)
    try:
        container.create_item(body=data)
        return jsonify({"message": "Competition created successfully"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Fetch data from Azure Cosmos DB based on CompetitionId
@app.route('/competition/<competition_id>', methods=['GET'])
def get_competition(competition_id):
    try:
        item = container.read_item(item=competition_id, partition_key=competition_id)
        return jsonify(item), 200
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
        container.delete_item(item=competition_id, partition_key=competition_id)
        return jsonify({"message": "Competition deleted successfully"}), 200
    except exceptions.CosmosResourceNotFoundError:
        return jsonify({"error": "Competition not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0")
