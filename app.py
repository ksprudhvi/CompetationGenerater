import os
import uuid
from datetime import datetime, timedelta
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import Flask, request, jsonify
from azure.cosmos import CosmosClient, exceptions
import config
from flask_cors import CORS
import string
import random
import azure.cosmos.exceptions as exceptions
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient, generate_blob_sas, BlobSasPermissions
from reportlab.lib.colors import black, grey, white, darkblue, darkred, lightgrey
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.enums import TA_CENTER, TA_LEFT


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
        ImageUrl=ImageUrl.json
        if(request.form['EventType']=='Banner'):
            saveBannerUrls(ImageUrl['ImageUrl'],request.form['EventId'])
        return ImageUrl
    except Exception as e:
        return jsonify({"error": str(e)}), 500
def saveBannerUrls(ImageUrl, BannerId):
    # Create a dictionary to hold the data
    data = {}
    
    # Populate the dictionary with the provided data
    data["id"] = generate_unique_id()  # Generate a unique id
    data["BannerId"] = BannerId
    data["imageUrl"] = ImageUrl
    data["CreationDateTimeStamp"] = datetime.now().isoformat()  # Capture the current timestamp
    
    # Get the container client for the 'BannerImgUrls' container
    container = database.get_container_client("BannerImgUrls")
    
    # Insert the data into the container (Create an item)
    try:
        container.create_item(body=data)
        print(f"Item with id {data['id']} created successfully!")
    except Exception as e:
        print(f"An error occurred: {e}")


@app.route('/getBanners', methods=['GET'])
def get_banner():
    try:
        # Get the container client inside the function
        container = database.get_container_client("BannerImgUrls")
        
        # Query to get all items from the container
        banners = list(container.read_all_items())
        
        # Return the data as JSON
        return jsonify(banners), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500      
@app.route('/removeBanner', methods=['POST'])
def remove_banner():
    try:
        # Get the container client
        container = database.get_container_client("BannerImgUrls")
        
        # Get the BannerId from the POST request body
        data = request.get_json()
        banner_id = data.get("BannerId")
        
        if not banner_id:
            return jsonify({"error": "BannerId is required"}), 400

        # Query to find the item based on the BannerId
        query = f"SELECT * FROM c WHERE c.BannerId = '{banner_id}'"
        items = list(container.query_items(query=query, enable_cross_partition_query=True))
        
        if not items:
            return jsonify({"error": "Banner not found"}), 404

        # Delete the item(s) based on BannerId
        for item in items:
            container.delete_item(item, partition_key=item['id'])

        return jsonify({"message": f"Banner with BannerId {banner_id} deleted successfully"}), 200
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
    
    # Ensure EventId is in the data
    if "EventId" not in data:
        return jsonify({"error": "EventId is required"}), 400
    data["id"] = generate_unique_id()
    data["status"] = "Scheduled"
    data["CreationDateTimeStamp"]= datetime.now().isoformat()
    container = database.get_container_client("EventMeta")
    # Query to check if a competition with the given EventId already exists
    query = "SELECT * FROM c WHERE c.EventId = @EventId"
    query_params = [
        {"name": "@EventId", "value": data["EventId"]}
    ]

    try:
        # Check if the competition already exists
        existing_items = list(container.query_items(
            query=query,
            parameters=query_params,
            enable_cross_partition_query=True
        ))
        if existing_items:
            # If the competition exists, replace it
            existing_item = existing_items[0]
            updated_item = container.replace_item(item=existing_item['id'], body=data)
            return jsonify({"eventId": data["EventId"]}), 200
        else:
            # If the competition does not exist, create a new one
            new_item = container.create_item(body=data)
            return jsonify({"eventId": data["EventId"]}), 201
    except exceptions.CosmosResourceNotFoundError:
        # Handle the case where the container or database does not exist
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        # Handle other Cosmos DB errors
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        # Handle any other exceptions
        return jsonify({"error": str(e)}), 500


@app.route('/updateTeams', methods=['POST'])
def createTeams():
    data = request.json
    # Ensure EventId is in the data
    if "EventId" not in data:
        return jsonify({"error": "EventId is required"}), 400
    # Generate a unique ID for the record (if necessary)
    data["id"] = generate_unique_id()
    data["CreationDateTimeStamp"]= datetime.now().isoformat()
    container = database.get_container_client("EventTeamsJudges")
    try:
        # Check if the record with the given EventId already exists
        query = "SELECT * FROM c WHERE c.EventId=@eventId"
        parameters = [{"name": "@eventId", "value": data["EventId"]}]
        existing_records = list(container.query_items(query=query, parameters=parameters, enable_cross_partition_query=True))
        if existing_records:
            # Record exists, update it
            existing_record = existing_records[0]
            # Update the existing record with new data
            container.replace_item(item=existing_record["id"], body=data)
            configureEventOrderMain(data) 
            return jsonify({"eventId": data["EventId"]}), 200
        else:
            # Record does not exist, create a new one
            container.create_item(body=data)
            configureEventOrderMain(data) 
            return jsonify({"eventId": data["EventId"]}), 201
    except exceptions.CosmosResourceNotFoundError:
        # Handle the case where the container or database does not exist
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        # Handle other Cosmos DB errors
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        # Handle any other exceptions
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
        
        # Define the scorecard access token document
        scorecardAccessTokens = {
            'id': generate_unique_id(),
            'EventId': data["EventId"],
            'judgeId': judge_id,
            'judgeName': judge_name,
            'HostAccess': False,
            'JudgeAccess': True,
            'CoachAccess': False,
            'TokenId': generate_token(),
            'CreationDateTimeStamp':datetime.now().isoformat()
        }

        # Query to check if token already exists for this judge and event
        query = "SELECT * FROM c WHERE c.EventId = @EventId AND c.judgeId = @judgeId"
        query_params = [
            {"name": "@EventId", "value": data["EventId"]},
            {"name": "@judgeId", "value": judge_id}
        ]

        try:
            # Check for existing tokens
            existing_tokens = list(accessTokenContainer.query_items(
                query=query,
                parameters=query_params,
                enable_cross_partition_query=True
            ))

            if existing_tokens:
                # If token exists, replace it
                existing_token = existing_tokens[0]
                scorecardAccessTokens['TokenId']=existing_token['TokenId']
                updated_token = accessTokenContainer.replace_item(item=existing_token['id'], body=scorecardAccessTokens)
                print(f"Updated access token for judge {judge_id}: {updated_token}")
            else:
                # If token does not exist, create a new one
                created_token = accessTokenContainer.create_item(body=scorecardAccessTokens)
                print(f"Created new access token for judge {judge_id}: {created_token}")
                
        except exceptions.CosmosHttpResponseError as e:
            # Log the error and continue; individual token creation or replacement failures should not stop the process
            print(f"Failed to process access token for judge {judge_id}: {e}")
        except Exception as e:
            # Handle unexpected errors
            print(f"Unexpected error for judge {judge_id}: {e}")


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
            'TokenId':generate_token(),
            'CreationDateTimeStamp':datetime.now().isoformat()
        }
        try: # Insert scorecard document into container
            accessTokenContainer.create_item(body=scorecardAccessTokens)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route('/CreateHostAccess', methods=['POST'])
def generateAccessTokensHostAccess():
    data=request.json
    HostConatiner = database.get_container_client("EventHostMeta")
    scorecardAccessTokens = {
        'id':generate_unique_id(),
        'HostId':generate_unique_id(),
        'Email':data['Email'],
        'CreationDateTimeStamp':datetime.now().isoformat()
    }
    accessTokenContainer = database.get_container_client("HostAccessRequests")
    try:
        # Insert scorecard document into container
        HostConatiner.create_item(body=scorecardAccessTokens)
        query = f"SELECT * FROM HostAccessRequests c WHERE c.Email = '{data['Email']}'"
        items = list(accessTokenContainer.query_items(query=query, enable_cross_partition_query=True))

        # If item(s) found, delete them
        for item in items:
            accessTokenContainer.delete_item(item=item['id'], partition_key=item['id'])
        
        return jsonify({"message": "Successfully Created Host Access"}), 200
        return jsonify({"message": "Successfully Created Host Access "}), 200
    except Exception as e:
        print("this is tyhe error"+e)
        return jsonify({"error": str(e)}), 500
import random
import string

def generate_code(length=6):
    characters = string.ascii_letters + string.digits
    code = ''.join(random.choice(characters) for _ in range(length))
    return code

# Example usage
print(generate_code(6))  # Generates a 6-character random code




GMAIL_USER = 'kprudhvi25@gmail.com'
GMAIL_APP_PASSWORD = 'avxk nhcn yqtu eznf'

@app.route('/SentOtp', methods=['POST'])
def SentOtp():
    data = request.json
    emails = data['Email']
    recipient = emails
    subject = 'Email OTP Verification'
    html_content = read_html_content("emailInvite.html")
    otp = generate_code(6)
    
    # Save OTP to the database
    accessTokenContainer = database.get_container_client("OtpMeta")
    otpDoc = {
        'id': generate_unique_id(),
        'Email': data['Email'],
        'Otp': otp,
        'CreationDateTimeStamp': datetime.now().isoformat()
    }
    accessTokenContainer.create_item(body=otpDoc)
    
    # Format the email content with OTP
    html_content = format_html_content(html_content, otpDoc)
    layout = read_html_content("scorecardLayout.html")
    emailContent = {'mailContent': html_content}
    html_content = format_html_content(layout, emailContent)

    try:
        # Create the email message
        msg = MIMEMultipart()
        msg['From'] = GMAIL_USER
        msg['To'] = recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(html_content, 'html'))
        
        # Connect to Gmail's SMTP server
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()  # Upgrade the connection to secure
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, recipient, msg.as_string())
        
        return jsonify({'message': 'Email sent successfully'})
    except Exception as e:
        return jsonify({'error': str(e)})
    
@app.route('/OtpVerification', methods=['POST'])
def OtpVerification():
    data=request.json
    otpContainer = database.get_container_client("OtpMeta")
    try:
        validationQuery = f"SELECT * FROM c WHERE c.Email = '{data['Email']}' AND c.Otp = '{data['OTP_CODE']}'"
        Tokens = list(otpContainer.query_items(query=validationQuery, enable_cross_partition_query=True))
        if(len(Tokens)>0):
            result={'validation':'true'}
        else:
            result={'validation':'false'}
        return jsonify(result), 200
        # Insert scorecard document into container
    except Exception as e:
        return jsonify({"error": str(e)}), 500   
# Define the function to delete old OTP entries
# def delete_old_otps():
#     ten_minutes_ago = datetime.now() - timedelta(minutes=10)
#     query = "SELECT * FROM c WHERE c.CreationDateTimeStamp < @timestamp"
#     parameters = [{'name': '@timestamp', 'value': ten_minutes_ago.isoformat()}]
#     otpContainer = database.get_container_client("OtpMeta")
#     old_otps = otpContainer.query_items(query=query, parameters=parameters, enable_cross_partition_query=True)
#     for otp in old_otps:
#         otpContainer.delete_item(item=otp, partition_key=otp['id'])

# # Setup APScheduler to run the delete_old_otps function every minute
# scheduler = BackgroundScheduler()
# scheduler.add_job(delete_old_otps, 'interval', minutes=1)
# scheduler.start()     
@app.route('/createLoginDetails', methods=['POST'])
def createAccount():
    data=request.json
    accessTokenContainer = database.get_container_client("EventAuthKeys")
    scorecardAccessTokens = {
        'id':generate_unique_id(),
        'Email':data['Email'],
        'Password':data['Password'],
        'CreationDateTimeStamp':datetime.now().isoformat()
    }
    try:
        # Insert scorecard document into container
        accessTokenContainer.create_item(body=scorecardAccessTokens)
        if(data['HostAccessRequest']=='true'):
            RequestContainer = database.get_container_client("HostAccessRequests")
            RequestContainer.create_item(body=scorecardAccessTokens)
        return jsonify({"message": "Successfully Created Account "}), 200
    except Exception as e:
        print("this is tyhe error"+e)
        return jsonify({"error": str(e)}), 500

@app.route('/approveHostAccess', methods=['POST'])
def approveHostAccess():
    data=request.json
    result={}
    accessTokenContainer = database.get_container_client("HostAccessRequests")
    try:
        container = database.get_container_client("EventMeta")
        query = "SELECT * FROM c"
        items = accessTokenContainer.query_items(query=query, enable_cross_partition_query=True)
        result = list(items)
        return jsonify(result), 200
        # Insert scorecard document into container
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/authLoginDetails', methods=['POST'])
def authLoginDetails():
    data=request.json
    result={}
    accessTokenContainer = database.get_container_client("EventAuthKeys")
    try:
        validationQuery = f"SELECT * FROM c WHERE c.Email = '{data['Email']}' AND c.Password = '{data['Password']}'"
        Tokens = list(accessTokenContainer.query_items(query=validationQuery, enable_cross_partition_query=True))
        if(len(Tokens)>0):
            accessTokenContainer = database.get_container_client("EventHostMeta")
            validationQuery = f"SELECT * FROM c WHERE c.Email = '{data['Email']}'"
            access=list(accessTokenContainer.query_items(query=validationQuery, enable_cross_partition_query=True))
            if(len(access)>0):
                result={'validation':'true','HostAccess':'true','HostId':access[0]['HostId'],'OwnerAccess':'true' if data['Email'] == 'nandhashriramsabbina@outlook.com' else 'false'}
            else:
                result={'validation':'true','HostAccess':'false','OwnerAccess':'true' if data['Email'] == 'nandhashriramsabbina@outlook.com' else 'false'}    
        else:
            result={'validation':'false','HostAccess':'false','OwnerAccess':'true' if data['Email'] == 'nandhashriramsabbina@outlook.com' else 'false'}
        return jsonify(result), 200
        # Insert scorecard document into container
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
    
#saveScoreParameters   

@app.route('/saveScoreParameters', methods=['POST'])
def update_Scorecard():
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
    
@app.route('/getBanners', methods=['GET'])
def getBanners():
    try:
        container = database.get_container_client("BannerImgUrls")
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
    
def get_category_entry(scorecardMeta, category_name):
    return next((entry for entry in scorecardMeta if entry['category'] == category_name), None)

def add_scorecard(data):
    competition_id = data.get('EventId')

    # Initialize Cosmos Client
    container = database.get_container_client("EventMeta")
    query = f"SELECT c.eventCategory, c.scorecardMeta FROM c WHERE c.EventId = '{competition_id}'"

    try:
        # Fetch event category and scorecard meta
        items = container.query_items(query=query, enable_cross_partition_query=True)
        eventCategorys = list(items)
        if not eventCategorys:
            return jsonify({"error": "No event category found for the given EventId"}), 404

        eventCategorys = eventCategorys[0]
        eventScoreCardMeta = eventCategorys.get('scorecardMeta', [])
        eventCategorys = eventCategorys.get('eventCategory', [])

        # Initialize the scorecard container client
        scorecard_container = database.get_container_client("EventScoreCard")

        # Create scorecard entry for every judge * team combination
        for category in eventCategorys:
            for judge in data.get('JudegsInfo', []):
                judge_id = judge.get('id')
                judge_name = judge.get('name')
                for team in data.get('teamsInfo', []):
                    team_id = team.get('teamName', {}).get('id')
                    team_name = team.get('teamName', {}).get('name')

                    # Check for existing scorecard
                    unique_query = f"SELECT c.id FROM c WHERE c.EventId = '{data['EventId']}' AND c.judgeId = '{judge_id}' AND c.teamId = '{team_id}' AND c.category = '{category}'"
                    existing_entries = list(scorecard_container.query_items(query=unique_query, enable_cross_partition_query=True))

                    if existing_entries:
                        # Skip creating the entry if it already exists
                        continue

                    # Initialize scorecard with dynamic fields based on scorecardMeta
                    scorecard = {param['name']: 0 for param in get_category_entry(eventScoreCardMeta, category).get('parameters', [])}
                    scorecard['total'] = 0  # Initialize total score

                    # Create initial scorecard document
                    scorecard_document = {
                        'id': generate_unique_id(),
                        'EventId': data["EventId"],
                        'judgeId': judge_id,
                        'judgeName': judge_name,
                        'teamId': team_id,
                        'teamName': team_name,
                        'category': category,
                        'teamMemberId': None,  # Assuming we don't have specific team member ID here
                        'scorecard': scorecard,
                        'comments': '',
                        'CreationDateTimeStamp': datetime.now().isoformat()
                    }

                    # Insert scorecard document into container
                    try:
                        scorecard_container.create_item(body=scorecard_document)
                    except Exception as e:
                        return jsonify({"error": str(e)}), 500

        return jsonify({"status": "Scorecards created successfully"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/update_scores', methods=['POST'])
def update_scores():
    try:
        data = request.json
        scorecard_id=data["id"]
        eventId=data["EventId"]
        new_scores=data["scorecard"]
        comments=data["comment"]
        scorecard_container = database.get_container_client("EventScoreCard")
        # Retrieve the scorecard document from the database
        scorecard_document = scorecard_container.read_item(item=scorecard_id,partition_key=eventId)
        # Update the scores in the scorecard document
        scorecard_document['scorecard'].update(new_scores)
        scorecard_document['comments']=comments
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
        category=data.get('category')
        if not competition_id or not judge_id:
            return jsonify({"error": "Please provide both competitionId and judgeId in the request body"}), 400
        scorecard_container = database.get_container_client("EventScoreCard")
            # Query scorecards for the given competition_id and judge_id
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}' AND c.judgeId = '{judge_id}' AND c.teamId='{teamId}' AND c.category='{category}'"
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
        competition_id = data.get('EventId')

        # Initialize Cosmos DB container
        scorecard_container = database.get_container_client("EventScoreCard")
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
        scorecards = list(scorecard_container.query_items(query=query, enable_cross_partition_query=True))

        # Initialize dictionary to store scores per category
        category_scores = {}

        # Process each scorecard entry
        for scorecard in scorecards:
            team_id = scorecard.get('teamId')
            team_name = scorecard.get('teamName')
            category = scorecard.get('category')
            scorecard_data = scorecard.get('scorecard', {})

            # Compute score dynamically, excluding 'total'
            score_fields = [key for key in scorecard_data if key != 'total']
            score = sum(scorecard_data.get(field, 0) for field in score_fields)

            # Create a unique key for each team per category
            team_category_key = (team_name, category)

            if category not in category_scores:
                category_scores[category] = {}

            if team_category_key not in category_scores[category]:
                category_scores[category][team_category_key] = {
                    'teamId': team_id,
                    'teamName': team_name,
                    'category': category,
                    'total_score': 0
                }

            category_scores[category][team_category_key]['total_score'] += score

        # Prepare leaderboard sorted by categories and scores
        leaderboard = {}
        for category, scores in category_scores.items():
            sorted_scores = sorted(scores.values(), key=lambda x: x['total_score'], reverse=True)
            leaderboard[category] = sorted_scores

        return jsonify({"leaderboard": leaderboard}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


OUTLOOK_USER='nandhashriramsabbina@outlook.com'
OUTLOOK_PASSWORD='eakwnysdkybugfuh'  # Use App Password if 2-Step Verification is enabled
def read_html_content(file_path):
    with open(file_path, 'r') as file:
        return file.read()

@app.route('/send-email', methods=['POST'])
def send_email():
    data=request.json
    emails = data['emails']
    recipient = ', '.join(emails)
    recipient=recipient.split(",")
    subject = 'Test'
    html_content = read_html_content("emailInvite.html")
    formatted_html = format_html_content(html_content, entry)
    html_content.replace("PLACEHOLDER_COMPANY_NAME","Productions")
    html_content.replace("PLACEHOLDER_EVENT_TITLE","Productions")
    try:
        # Create the email message
        msg = MIMEMultipart()
        msg['From'] = GMAIL_USER
        msg['To'] = recipient
        msg['Subject'] = subject
        layout = read_html_content("scorecardLayout.html")
        emailContent={'mailContent':html_content}
        html_content = format_html_content(layout, emailContent)
        msg.attach(MIMEText(html_content, 'html'))
        # Connect to Gmail's SMTP server
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()  # Upgrade the connection to secure
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, recipient, msg.as_string())
    except Exception as e:
            print( jsonify({'error': str(e)}))
    return jsonify({'message': 'Email sent successfully with PDF attachment'})
def format_html_content(template, data):
    for key, value in data.items():
        placeholder = '{{' + key + '}}'
        template = template.replace(placeholder, str(value))
    return template



@app.route('/send-scorecard', methods=['POST'])
def sendScoreCardsemail():
    data=request.json
    pdf_filename="ScoreCard.pdf"
    competition_id=data['EventId']
    container = database.get_container_client("EventMeta")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    items = container.query_items(query=query, enable_cross_partition_query=True)
    metaData = list(items)
    metaData=metaData[0]
    container = database.get_container_client("EventTeamsJudges")
    query=f"SELECT *  FROM c WHERE c.EventId = '{competition_id}' "
    emailsData = list(container.query_items(query=query, enable_cross_partition_query=True))
    # Extract emails
    emails = []
    scorecard_container = database.get_container_client("EventScoreCard")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    scorecards = list(scorecard_container.query_items(query=query, enable_cross_partition_query=True))
    for entry in scorecards:
        subject="Score Card by "+entry['judgeName']+' for '+entry['category']
        entry['titleHeading']="Score Card For "+entry['category']
        entry['eventTitle']=metaData['eventTitle']
        for iteam in entry['scorecard']:
            entry[iteam]=entry['scorecard'][iteam]
        html_content = read_html_content("ScoreCard.html")
        formatted_html = format_html_content(html_content, entry)
        specific_team_id = entry['teamId']
        emails = []
        for event in emailsData:
            for team in event.get('teamsInfo', []):
                if team['teamName']['id'] == specific_team_id:
                    if team['teamRepresentativeEmail']['email']:
                        emails.append(team['teamRepresentativeEmail']['email'])
                    if team['coachName']['email']:
                        emails.append(team['coachName']['email'])
                    if team['DirectorName']['email']:
                        emails.append(team['DirectorName']['email'])
        createScoreCardPdf(entry['judgeName']+'_ScoreCard.pdf',entry)
        emails = list(filter(None, set(emails)))
        recipient = ', '.join(emails)
        recipient=recipient.split(",")
        for entry in recipient:
            try:
                # Create the email message
                msg = MIMEMultipart()
                msg['From'] = GMAIL_USER
                msg['To'] = entry
                msg['Subject'] = subject
                layout = read_html_content("scorecardLayout.html")
                emailContent={'mailContent':formatted_html}
                html_content = format_html_content(layout, emailContent)
                msg.attach(MIMEText(html_content, 'html'))

                with open(pdf_filename, 'rb') as pdf_file:
                    pdf_attachment = MIMEApplication(pdf_file.read(), _subtype='pdf')
                    pdf_attachment.add_header('Content-Disposition', 'attachment', filename=pdf_filename)
                    msg.attach(pdf_attachment)
                # Connect to Gmail's SMTP server
                with smtplib.SMTP('smtp.gmail.com', 587) as server:
                    server.starttls()  # Upgrade the connection to secure
                    server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                    server.sendmail(GMAIL_USER, recipient, msg.as_string())
            except Exception as e:
                return jsonify({'error': str(e)})
    return jsonify({'message': "success"})
def configureEventOrder(data):
    competition_id = data['EventId']
    scorecard_container = database.get_container_client("EventScoreCard")
    # Query scorecards for the given competition_id
    query = f"SELECT c.category, c.teamId, c.teamName FROM c WHERE c.EventId = @EventId"
    query_params = [{"name": "@EventId", "value": competition_id}]
    listPerformances = list(scorecard_container.query_items(
        query=query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))

    eventOrder_document = {
        "id": generate_unique_id(),
        "EventId": competition_id,
        "categoryOrder": []
    }

    seen = set()
    unique_listPerformances = []
    for performance in listPerformances:
        identifier = (performance['category'], performance['teamId'], performance['teamName'])
        if identifier not in seen:
            seen.add(identifier)
            unique_listPerformances.append(performance)

    # Organize performances by category
    categories = {}
    for performance in unique_listPerformances:
        category = performance.get("category")
        team_id = performance.get("teamId")
        team_name = performance.get("teamName")

        if category not in categories:
            categories[category] = []

        categories[category].append({
            "teamId": team_id,
            "teamName": team_name,
        })

    for category_index, (category, teams) in enumerate(categories.items(), start=1):
        eventOrder_document["categoryOrder"].append({
            "category": category,
            "order": category_index,
            "performances": []
        })

        for team_index, team in enumerate(teams, start=1):
            team_with_order = team.copy()
            team_with_order["order"] = team_index
            eventOrder_document["categoryOrder"][-1]["performances"].append(team_with_order)

    # Container for EventOrderConfig
    Ordercontainer = database.get_container_client("EventOrderConfig")
    
    try:
        # Check if the event order document already exists
        existing_documents = list(Ordercontainer.query_items(
            query="SELECT * FROM c WHERE c.EventId = @EventId",
            parameters=query_params,
            enable_cross_partition_query=True
        ))

        if existing_documents:
            # If exists, replace the document
            existing_document = existing_documents[0]
            updated_document = Ordercontainer.replace_item(item=existing_document['id'], body=eventOrder_document)
            return jsonify(updated_document), 200
        else:
            # If does not exist, create a new document
            eventOrder_document["CreationDateTimeStamp"]=datetime.now().isoformat()
            new_document = Ordercontainer.create_item(body=eventOrder_document)
            return jsonify(new_document), 201

    except exceptions.CosmosResourceNotFoundError:
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
def configureEventOrderMain(data):
    competition_id = data['EventId']
    container = database.get_container_client("EventTeamsJudges")
    meta_conatiner = database.get_container_client("EventMeta")
    # Query scorecards for the given competition_id
    query = f"SELECT c.teamsInfo FROM c WHERE c.EventId = @EventId"
    category_query=f"SELECT c.eventCategory FROM c WHERE c.EventId = @EventId"
    query_params = [{"name": "@EventId", "value": competition_id}]
    listCategory = list(meta_conatiner.query_items(
        query=category_query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))
    listPerformances = list(container.query_items(
        query=query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))

    eventOrder_document = {
        "id": generate_unique_id(),
        "EventId": competition_id,
        "categoryOrder": []
    }

    seen = set()
    unique_listPerformances = []
    for category in listCategory[0]['eventCategory']:
        for performance in listPerformances[0]['teamsInfo']:
            identifier = (category, performance['teamName']['id'], performance['teamName']['name'])
            data = {
            'category': category,
            'teamId': performance['teamName']['id'],
            'teamName': performance['teamName']['name']
            }
            if identifier not in seen:
                seen.add(identifier)
                unique_listPerformances.append(data)

    # Organize performances by category
    categories = {}
    for performance in unique_listPerformances:
        category = performance.get("category")
        team_id = performance.get("teamId")
        team_name = performance.get("teamName")

        if category not in categories:
            categories[category] = []

        categories[category].append({
            "teamId": team_id,
            "teamName": team_name,
        })

    for category_index, (category, teams) in enumerate(categories.items(), start=1):
        eventOrder_document["categoryOrder"].append({
            "category": category,
            "order": category_index,
            "performances": []
        })

        for team_index, team in enumerate(teams, start=1):
            team_with_order = team.copy()
            team_with_order["order"] = team_index
            eventOrder_document["categoryOrder"][-1]["performances"].append(team_with_order)

    # Container for EventOrderConfig
    Ordercontainer = database.get_container_client("EventOrderConfig")
    
    try:
        # Check if the event order document already exists
        existing_documents = list(Ordercontainer.query_items(
            query="SELECT * FROM c WHERE c.EventId = @EventId",
            parameters=query_params,
            enable_cross_partition_query=True
        ))

        if existing_documents:
            # If exists, replace the document
            existing_document = existing_documents[0]
            updated_document = Ordercontainer.replace_item(item=existing_document['id'], body=eventOrder_document)
            return jsonify(updated_document), 200
        else:
            # If does not exist, create a new document
            eventOrder_document["CreationDateTimeStamp"]=datetime.now().isoformat()
            new_document = Ordercontainer.create_item(body=eventOrder_document)
            return jsonify(new_document), 201

    except exceptions.CosmosResourceNotFoundError:
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500        
@app.route('/getEventOrder', methods=['POST'])
def getEventOrder():
    Ordercontainer = database.get_container_client("EventOrderConfig")
    data=request.json
    competition_id=data['EventId']
    try:
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
        eventOrder_document = list(Ordercontainer.query_items(query=query, enable_cross_partition_query=True))
        return  eventOrder_document[0], 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route('/updateEventOrder', methods=['POST'])
def updateEventOrder():
    Ordercontainer = database.get_container_client("EventOrderConfig")
    data=request.json
    competition_id=data['EventId']
    order_id=data['id']
    try:
        updated_document = Ordercontainer.replace_item(item=order_id, body=data)
        return  updated_document, 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
def createScoreCardPdf(filename,data):
    try:
        doc = SimpleDocTemplate(filename, pagesize=letter)
        styles = getSampleStyleSheet()
        elements = []

        # Title
        title_style = styles['Title']
        title_style.fontName = 'Helvetica-Bold'
        title_style.fontSize = 24
        title_style.alignment = TA_CENTER
        title = Paragraph("Score Card", title_style)
        elements.append(title)
        elements.append(Spacer(1, 0.5 * inch))

        for entry in data:
            # Event Title
            event_title_style = styles['Heading1']
            event_title_style.fontName = 'Helvetica-Bold'
            event_title_style.fontSize = 20
            event_title_style.alignment = TA_CENTER
            event_title = Paragraph(f"{entry['eventTitle']}", event_title_style)
            elements.append(event_title)
            elements.append(Spacer(1, 0.25 * inch))

            # Judge and Team Details
            details_style = styles['Normal']
            details_style.fontName = 'Helvetica'
            details_style.fontSize = 12
            details_style.alignment = TA_LEFT
            judge_name = Paragraph(f"<b>Judge:</b> {entry['judgeName']}", details_style)
            team_name = Paragraph(f"<b>Team:</b> {entry['teamName']}", details_style)
            comments = Paragraph(f"<b>Comments:</b> {entry['Comments']}", details_style)
            elements.append(judge_name)
            elements.append(team_name)
            elements.append(comments)
            elements.append(Spacer(1, 0.5 * inch))

            # Performance Table
            table_data = [
                ["Category", "Score"],
                ["Creativity", entry['creativity']],
                ["Difficulty", entry['difficulty']],
                ["Formation", entry['formation']],
                ["Sync", entry['sync']],
                ["Technique", entry['technique']],
                ["Total", entry['total']]
            ]

            table = Table(table_data, colWidths=[2.5 * inch, 1.5 * inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4CAF50')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 0.5 * inch))

        # Build PDF
        doc.build(elements)
    except Exception as e:
         print(jsonify({"error": str(e)}), 500)


def create_pdf(filename, data,eventOrder):
    doc = SimpleDocTemplate(filename, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    title = Paragraph("Event Schedule", styles['Title'])
    elements.append(title)
    elements.append(Paragraph("<br/>", styles['Normal']))

    # Event Title
    event_id = Paragraph(f"{data.get('eventTitle', '')}", styles['Normal'])
    elements.append(event_id)
    elements.append(Paragraph("<br/>", styles['Normal']))
    # Event Venue String
    event_id = Paragraph(f"Venue :{data.get('eventVenue', '')}", styles['Normal'])
    elements.append(event_id)
    elements.append(Paragraph("<br/>", styles['Normal']))
    # Event Data String
    event_id = Paragraph(f"Date and Time :{data.get('eventDateString', '')}", styles['Normal'])
    elements.append(event_id)
    elements.append(Paragraph("<br/>", styles['Normal']))

    # Categories and Performances
    for category in eventOrder['categoryOrder']:
        category_title = Paragraph(f"<b>Category: {category['category']} (Order: {category['order']})</b>", styles['Heading2'])
        elements.append(category_title)
        # Table Data
        table_data = [["Order", "Team Name"]]  # Removed "Team ID"
        for performance in category['performances']:
            table_data.append([performance['order'], performance['teamName']])  # Removed "Team ID"
        # Create Table
        table = Table(table_data, colWidths=[1 * inch, 2.5 * inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 1, black),
        ]))
        elements.append(table)
        elements.append(Paragraph("<br/>", styles['Normal']))

    # Build PDF
    doc.build(elements)

# Route to send email with PDF attachment
@app.route('/sendEventSchedule', methods=['POST'])
def send_email_with_pdf():
    data = request.json
    competition_id = data.get('EventId')
    # Initialize Cosmos Client
    container = database.get_container_client("EventMeta")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    items = container.query_items(query=query, enable_cross_partition_query=True)
    eventCategorys = list(items)
    data=eventCategorys[0]
    query=f"SELECT *  FROM c WHERE c.EventId = '{competition_id}' "
    subject = (data.get('eventTitle', '') + '|' +
           data.get('eventDateString', '') + '|' +
           data.get('eventVenue', '') + ' Schedule')    # Create the PDF
    Ordercontainer = database.get_container_client("EventOrderConfig")
    competition_id=data['EventId']
    container = database.get_container_client("EventTeamsJudges")
    emailsData = list(container.query_items(query=query, enable_cross_partition_query=True))
    # Extract emails
    emails = []

# Extract team representative, coach, and director emails
    for event in emailsData:
        for team in event.get('teamsInfo', []):
            if team['teamRepresentativeEmail']['email']:
                emails.append(team['teamRepresentativeEmail']['email'])
            if team['coachName']['email']:
                emails.append(team['coachName']['email'])
            if team['DirectorName']['email']:
                emails.append(team['DirectorName']['email'])
    # Remove empty strings (if any) and duplicates
    emails = list(filter(None, set(emails)))
    recipient = ','.join(emails)
    recipient=recipient.split(",")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    eventOrder_document = list(Ordercontainer.query_items(query=query, enable_cross_partition_query=True))
    #create_pdf(pdf_filename, data,eventOrder_document[0])
    # Read and format HTML content
    firsthtml = read_html_content("EventSchedule-converted.html")
    firsthtml=format_html_content(firsthtml, data)
    for category in eventOrder_document[0]['categoryOrder']:
        html_content = read_html_content("categoryEventTag.html")
        tagData={}
        tagData['Category']=category['category']
        # Table Data
        table_data = [["Order", "Team Name"]]  # Removed "Team ID"
        orderTags=''
        for performance in category['performances']:
            perData={}
            entryTag = read_html_content("orderandTeamTag.html")
            perData['order']=performance['order']
            perData['TeamName']=performance['teamName']
            orderTags=orderTags+format_html_content(entryTag, perData)
        tagData['orderTags']  = orderTags
        firsthtml = firsthtml+format_html_content(html_content, tagData)
    firsthtml=firsthtml+read_html_content("EventScheduleEnd.html")
    for entry in recipient:
        try:
            # Create the email message
            msg = MIMEMultipart()
            msg['From'] = GMAIL_USER
            msg['To'] = entry
            msg['Subject'] = subject
            layout = read_html_content("scorecardLayout.html")
            emailContent={'mailContent':firsthtml}
            html_content = format_html_content(layout, emailContent)
            msg.attach(MIMEText(html_content, 'html'))


            # Connect to Gmail's SMTP server
            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.starttls()  # Upgrade the connection to secure
                server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                server.sendmail(GMAIL_USER, recipient, msg.as_string())
            # Clean up
        except Exception as e:
            print( jsonify({'error': str(e)}))
    return jsonify({'message': 'Email sent successfully with PDF attachment'})
        
if __name__ == "__main__":
    app.run(host="0.0.0.0",port=5001)



@app.route('/getBanners', methods=['GET'])
def get_banner():
    try:
        # Get the container client inside the function
        container = database.get_container_client("BannerImgUrls")
        
        # Query to get all items from the container
        banners = list(container.read_all_items())
        
        # Return the data as JSON
        return jsonify(banners), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500      
@app.route('/removeBanner', methods=['POST'])
def remove_banner():
    try:
        # Get the container client
        container = database.get_container_client("BannerImgUrls")
        
        # Get the BannerId from the POST request body
        data = request.get_json()
        banner_id = data.get("BannerId")
        
        if not banner_id:
            return jsonify({"error": "BannerId is required"}), 400

        # Query to find the item based on the BannerId
        query = f"SELECT * FROM c WHERE c.BannerId = '{banner_id}'"
        items = list(container.query_items(query=query, enable_cross_partition_query=True))
        
        if not items:
            return jsonify({"error": "Banner not found"}), 404

        # Delete the item(s) based on BannerId
        for item in items:
            container.delete_item(item, partition_key=item['id'])

        return jsonify({"message": f"Banner with BannerId {banner_id} deleted successfully"}), 200
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
    
    # Ensure EventId is in the data
    if "EventId" not in data:
        return jsonify({"error": "EventId is required"}), 400
    data["id"] = generate_unique_id()
    data["status"] = "Scheduled"
    data["CreationDateTimeStamp"]= datetime.now().isoformat()
    container = database.get_container_client("EventMeta")
    # Query to check if a competition with the given EventId already exists
    query = "SELECT * FROM c WHERE c.EventId = @EventId"
    query_params = [
        {"name": "@EventId", "value": data["EventId"]}
    ]

    try:
        # Check if the competition already exists
        existing_items = list(container.query_items(
            query=query,
            parameters=query_params,
            enable_cross_partition_query=True
        ))
        if existing_items:
            # If the competition exists, replace it
            existing_item = existing_items[0]
            updated_item = container.replace_item(item=existing_item['id'], body=data)
            return jsonify({"eventId": data["EventId"]}), 200
        else:
            # If the competition does not exist, create a new one
            new_item = container.create_item(body=data)
            return jsonify({"eventId": data["EventId"]}), 201
    except exceptions.CosmosResourceNotFoundError:
        # Handle the case where the container or database does not exist
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        # Handle other Cosmos DB errors
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        # Handle any other exceptions
        return jsonify({"error": str(e)}), 500


@app.route('/updateTeams', methods=['POST'])
def createTeams():
    data = request.json
    # Ensure EventId is in the data
    if "EventId" not in data:
        return jsonify({"error": "EventId is required"}), 400
    # Generate a unique ID for the record (if necessary)
    data["id"] = generate_unique_id()
    data["CreationDateTimeStamp"]= datetime.now().isoformat()
    container = database.get_container_client("EventTeamsJudges")
    try:
        # Check if the record with the given EventId already exists
        query = "SELECT * FROM c WHERE c.EventId=@eventId"
        parameters = [{"name": "@eventId", "value": data["EventId"]}]
        existing_records = list(container.query_items(query=query, parameters=parameters, enable_cross_partition_query=True))
        if existing_records:
            # Record exists, update it
            existing_record = existing_records[0]
            # Update the existing record with new data
            container.replace_item(item=existing_record["id"], body=data)
            configureEventOrderMain(data) 
            return jsonify({"eventId": data["EventId"]}), 200
        else:
            # Record does not exist, create a new one
            container.create_item(body=data)
            configureEventOrderMain(data) 
            return jsonify({"eventId": data["EventId"]}), 201
    except exceptions.CosmosResourceNotFoundError:
        # Handle the case where the container or database does not exist
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        # Handle other Cosmos DB errors
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        # Handle any other exceptions
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
        
        # Define the scorecard access token document
        scorecardAccessTokens = {
            'id': generate_unique_id(),
            'EventId': data["EventId"],
            'judgeId': judge_id,
            'judgeName': judge_name,
            'HostAccess': False,
            'JudgeAccess': True,
            'CoachAccess': False,
            'TokenId': generate_token(),
            'CreationDateTimeStamp':datetime.now().isoformat()
        }

        # Query to check if token already exists for this judge and event
        query = "SELECT * FROM c WHERE c.EventId = @EventId AND c.judgeId = @judgeId"
        query_params = [
            {"name": "@EventId", "value": data["EventId"]},
            {"name": "@judgeId", "value": judge_id}
        ]

        try:
            # Check for existing tokens
            existing_tokens = list(accessTokenContainer.query_items(
                query=query,
                parameters=query_params,
                enable_cross_partition_query=True
            ))

            if existing_tokens:
                # If token exists, replace it
                existing_token = existing_tokens[0]
                scorecardAccessTokens['TokenId']=existing_token['TokenId']
                updated_token = accessTokenContainer.replace_item(item=existing_token['id'], body=scorecardAccessTokens)
                print(f"Updated access token for judge {judge_id}: {updated_token}")
            else:
                # If token does not exist, create a new one
                created_token = accessTokenContainer.create_item(body=scorecardAccessTokens)
                print(f"Created new access token for judge {judge_id}: {created_token}")
                
        except exceptions.CosmosHttpResponseError as e:
            # Log the error and continue; individual token creation or replacement failures should not stop the process
            print(f"Failed to process access token for judge {judge_id}: {e}")
        except Exception as e:
            # Handle unexpected errors
            print(f"Unexpected error for judge {judge_id}: {e}")


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
            'TokenId':generate_token(),
            'CreationDateTimeStamp':datetime.now().isoformat()
        }
        try: # Insert scorecard document into container
            accessTokenContainer.create_item(body=scorecardAccessTokens)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route('/CreateHostAccess', methods=['POST'])
def generateAccessTokensHostAccess():
    data=request.json
    HostConatiner = database.get_container_client("EventHostMeta")
    scorecardAccessTokens = {
        'id':generate_unique_id(),
        'HostId':generate_unique_id(),
        'Email':data['Email'],
        'CreationDateTimeStamp':datetime.now().isoformat()
    }
    accessTokenContainer = database.get_container_client("HostAccessRequests")
    try:
        # Insert scorecard document into container
        HostConatiner.create_item(body=scorecardAccessTokens)
        query = f"SELECT * FROM HostAccessRequests c WHERE c.Email = '{data['Email']}'"
        items = list(accessTokenContainer.query_items(query=query, enable_cross_partition_query=True))

        # If item(s) found, delete them
        for item in items:
            accessTokenContainer.delete_item(item=item['id'], partition_key=item['id'])
        
        return jsonify({"message": "Successfully Created Host Access"}), 200
        return jsonify({"message": "Successfully Created Host Access "}), 200
    except Exception as e:
        print("this is tyhe error"+e)
        return jsonify({"error": str(e)}), 500
import random
import string

def generate_code(length=6):
    characters = string.ascii_letters + string.digits
    code = ''.join(random.choice(characters) for _ in range(length))
    return code

# Example usage
print(generate_code(6))  # Generates a 6-character random code

CLIENT_ID = 'd7b1ed96-6e95-4354-af2a-544869f09e55'
CLIENT_SECRET = 'cfc8Q~2epL9FdAtlvwCEjwCmvrsJ-dDVKSj1Zclo'
TENANT_ID = 'eccdeba0-716d-4614-9824-ff4754cf84a9'
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["https://graph.microsoft.com/.default"]



# MSAL client instance
app_msal = ConfidentialClientApplication(
    CLIENT_ID,
    authority=AUTHORITY,
    client_credential=CLIENT_SECRET
)

GMAIL_USER = 'nandhasriramsabbina@gmail.com'
GMAIL_APP_PASSWORD = 'fngm ypaw glfo tgvo'

@app.route('/SentOtp', methods=['POST'])
def SentOtp():
    data = request.json
    emails = data['Email']
    recipient = emails
    subject = 'Email OTP Verification'
    html_content = read_html_content("emailInvite.html")
    otp = generate_code(6)
    
    # Save OTP to the database
    accessTokenContainer = database.get_container_client("OtpMeta")
    otpDoc = {
        'id': generate_unique_id(),
        'Email': data['Email'],
        'Otp': otp,
        'CreationDateTimeStamp': datetime.now().isoformat()
    }
    accessTokenContainer.create_item(body=otpDoc)
    
    # Format the email content with OTP
    html_content = format_html_content(html_content, otpDoc)
    layout = read_html_content("scorecardLayout.html")
    emailContent = {'mailContent': html_content}
    html_content = format_html_content(layout, emailContent)

    try:
        # Create the email message
        msg = MIMEMultipart()
        msg['From'] = GMAIL_USER
        msg['To'] = recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(html_content, 'html'))
        
        # Connect to Gmail's SMTP server
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()  # Upgrade the connection to secure
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, recipient, msg.as_string())
        
        return jsonify({'message': 'Email sent successfully'})
    except Exception as e:
        return jsonify({'error': str(e)})
    
@app.route('/OtpVerification', methods=['POST'])
def OtpVerification():
    data=request.json
    otpContainer = database.get_container_client("OtpMeta")
    try:
        validationQuery = f"SELECT * FROM c WHERE c.Email = '{data['Email']}' AND c.Otp = '{data['OTP_CODE']}'"
        Tokens = list(otpContainer.query_items(query=validationQuery, enable_cross_partition_query=True))
        if(len(Tokens)>0):
            result={'validation':'true'}
        else:
            result={'validation':'false'}
        return jsonify(result), 200
        # Insert scorecard document into container
    except Exception as e:
        return jsonify({"error": str(e)}), 500   
# Define the function to delete old OTP entries
# def delete_old_otps():
#     ten_minutes_ago = datetime.now() - timedelta(minutes=10)
#     query = "SELECT * FROM c WHERE c.CreationDateTimeStamp < @timestamp"
#     parameters = [{'name': '@timestamp', 'value': ten_minutes_ago.isoformat()}]
#     otpContainer = database.get_container_client("OtpMeta")
#     old_otps = otpContainer.query_items(query=query, parameters=parameters, enable_cross_partition_query=True)
#     for otp in old_otps:
#         otpContainer.delete_item(item=otp, partition_key=otp['id'])

# # Setup APScheduler to run the delete_old_otps function every minute
# scheduler = BackgroundScheduler()
# scheduler.add_job(delete_old_otps, 'interval', minutes=1)
# scheduler.start()     
@app.route('/createLoginDetails', methods=['POST'])
def createAccount():
    data=request.json
    accessTokenContainer = database.get_container_client("EventAuthKeys")
    scorecardAccessTokens = {
        'id':generate_unique_id(),
        'Email':data['Email'],
        'Password':data['Password'],
        'CreationDateTimeStamp':datetime.now().isoformat()
    }
    try:
        # Insert scorecard document into container
        accessTokenContainer.create_item(body=scorecardAccessTokens)
        if(data['HostAccessRequest']=='true'):
            RequestContainer = database.get_container_client("HostAccessRequests")
            RequestContainer.create_item(body=scorecardAccessTokens)
        return jsonify({"message": "Successfully Created Account "}), 200
    except Exception as e:
        print("this is tyhe error"+e)
        return jsonify({"error": str(e)}), 500

@app.route('/approveHostAccess', methods=['POST'])
def approveHostAccess():
    data=request.json
    result={}
    accessTokenContainer = database.get_container_client("HostAccessRequests")
    try:
        container = database.get_container_client("EventMeta")
        query = "SELECT * FROM c"
        items = accessTokenContainer.query_items(query=query, enable_cross_partition_query=True)
        result = list(items)
        return jsonify(result), 200
        # Insert scorecard document into container
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/authLoginDetails', methods=['POST'])
def authLoginDetails():
    data=request.json
    result={}
    accessTokenContainer = database.get_container_client("EventAuthKeys")
    try:
        validationQuery = f"SELECT * FROM c WHERE c.Email = '{data['Email']}' AND c.Password = '{data['Password']}'"
        Tokens = list(accessTokenContainer.query_items(query=validationQuery, enable_cross_partition_query=True))
        if(len(Tokens)>0):
            accessTokenContainer = database.get_container_client("EventHostMeta")
            validationQuery = f"SELECT * FROM c WHERE c.Email = '{data['Email']}'"
            access=list(accessTokenContainer.query_items(query=validationQuery, enable_cross_partition_query=True))
            if(len(access)>0):
                result={'validation':'true','HostAccess':'true','HostId':access[0]['HostId'],'OwnerAccess':'true' if data['Email'] == 'nandhashriramsabbina@outlook.com' else 'false'}
            else:
                result={'validation':'true','HostAccess':'false','OwnerAccess':'true' if data['Email'] == 'nandhashriramsabbina@outlook.com' else 'false'}    
        else:
            result={'validation':'false','HostAccess':'false','OwnerAccess':'true' if data['Email'] == 'nandhashriramsabbina@outlook.com' else 'false'}
        return jsonify(result), 200
        # Insert scorecard document into container
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
    
#saveScoreParameters   

@app.route('/saveScoreParameters', methods=['POST'])
def update_Scorecard():
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
    
@app.route('/getBanners', methods=['GET'])
def getBanners():
    try:
        container = database.get_container_client("BannerImgUrls")
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
    
def get_category_entry(scorecardMeta, category_name):
    return next((entry for entry in scorecardMeta if entry['category'] == category_name), None)

def add_scorecard(data):
    competition_id = data.get('EventId')

    # Initialize Cosmos Client
    container = database.get_container_client("EventMeta")
    query = f"SELECT c.eventCategory, c.scorecardMeta FROM c WHERE c.EventId = '{competition_id}'"

    try:
        # Fetch event category and scorecard meta
        items = container.query_items(query=query, enable_cross_partition_query=True)
        eventCategorys = list(items)
        if not eventCategorys:
            return jsonify({"error": "No event category found for the given EventId"}), 404

        eventCategorys = eventCategorys[0]
        eventScoreCardMeta = eventCategorys.get('scorecardMeta', [])
        eventCategorys = eventCategorys.get('eventCategory', [])

        # Initialize the scorecard container client
        scorecard_container = database.get_container_client("EventScoreCard")

        # Create scorecard entry for every judge * team combination
        for category in eventCategorys:
            for judge in data.get('JudegsInfo', []):
                judge_id = judge.get('id')
                judge_name = judge.get('name')
                for team in data.get('teamsInfo', []):
                    team_id = team.get('teamName', {}).get('id')
                    team_name = team.get('teamName', {}).get('name')

                    # Check for existing scorecard
                    unique_query = f"SELECT c.id FROM c WHERE c.EventId = '{data['EventId']}' AND c.judgeId = '{judge_id}' AND c.teamId = '{team_id}' AND c.category = '{category}'"
                    existing_entries = list(scorecard_container.query_items(query=unique_query, enable_cross_partition_query=True))

                    if existing_entries:
                        # Skip creating the entry if it already exists
                        continue

                    # Initialize scorecard with dynamic fields based on scorecardMeta
                    scorecard = {param['name']: 0 for param in get_category_entry(eventScoreCardMeta, category).get('parameters', [])}
                    scorecard['total'] = 0  # Initialize total score

                    # Create initial scorecard document
                    scorecard_document = {
                        'id': generate_unique_id(),
                        'EventId': data["EventId"],
                        'judgeId': judge_id,
                        'judgeName': judge_name,
                        'teamId': team_id,
                        'teamName': team_name,
                        'category': category,
                        'teamMemberId': None,  # Assuming we don't have specific team member ID here
                        'scorecard': scorecard,
                        'comments': '',
                        'CreationDateTimeStamp': datetime.now().isoformat()
                    }

                    # Insert scorecard document into container
                    try:
                        scorecard_container.create_item(body=scorecard_document)
                    except Exception as e:
                        return jsonify({"error": str(e)}), 500

        return jsonify({"status": "Scorecards created successfully"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/update_scores', methods=['POST'])
def update_scores():
    try:
        data = request.json
        scorecard_id=data["id"]
        eventId=data["EventId"]
        new_scores=data["scorecard"]
        comments=data["comment"]
        scorecard_container = database.get_container_client("EventScoreCard")
        # Retrieve the scorecard document from the database
        scorecard_document = scorecard_container.read_item(item=scorecard_id,partition_key=eventId)
        # Update the scores in the scorecard document
        scorecard_document['scorecard'].update(new_scores)
        scorecard_document['comments']=comments
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
        category=data.get('category')
        if not competition_id or not judge_id:
            return jsonify({"error": "Please provide both competitionId and judgeId in the request body"}), 400
        scorecard_container = database.get_container_client("EventScoreCard")
            # Query scorecards for the given competition_id and judge_id
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}' AND c.judgeId = '{judge_id}' AND c.teamId='{teamId}' AND c.category='{category}'"
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
        competition_id = data.get('EventId')

        # Initialize Cosmos DB container
        scorecard_container = database.get_container_client("EventScoreCard")
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
        scorecards = list(scorecard_container.query_items(query=query, enable_cross_partition_query=True))

        # Initialize dictionary to store scores per category
        category_scores = {}

        # Process each scorecard entry
        for scorecard in scorecards:
            team_id = scorecard.get('teamId')
            team_name = scorecard.get('teamName')
            category = scorecard.get('category')
            scorecard_data = scorecard.get('scorecard', {})

            # Compute score dynamically, excluding 'total'
            score_fields = [key for key in scorecard_data if key != 'total']
            score = sum(scorecard_data.get(field, 0) for field in score_fields)

            # Create a unique key for each team per category
            team_category_key = (team_name, category)

            if category not in category_scores:
                category_scores[category] = {}

            if team_category_key not in category_scores[category]:
                category_scores[category][team_category_key] = {
                    'teamId': team_id,
                    'teamName': team_name,
                    'category': category,
                    'total_score': 0
                }

            category_scores[category][team_category_key]['total_score'] += score

        # Prepare leaderboard sorted by categories and scores
        leaderboard = {}
        for category, scores in category_scores.items():
            sorted_scores = sorted(scores.values(), key=lambda x: x['total_score'], reverse=True)
            leaderboard[category] = sorted_scores

        return jsonify({"leaderboard": leaderboard}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


OUTLOOK_USER='nandhashriramsabbina@outlook.com'
OUTLOOK_PASSWORD='eakwnysdkybugfuh'  # Use App Password if 2-Step Verification is enabled
def read_html_content(file_path):
    with open(file_path, 'r') as file:
        return file.read()

@app.route('/send-email', methods=['POST'])
def send_email():
    data=request.json
    emails = data['emails']
    recipient = ', '.join(emails)
    recipient=recipient.split(",")
    subject = 'Test'
    html_content = read_html_content("emailInvite.html")
    formatted_html = format_html_content(html_content, entry)
    html_content.replace("PLACEHOLDER_COMPANY_NAME","Productions")
    html_content.replace("PLACEHOLDER_EVENT_TITLE","Productions")
    try:
        # Create the email message
        msg = MIMEMultipart()
        msg['From'] = GMAIL_USER
        msg['To'] = recipient
        msg['Subject'] = subject
        layout = read_html_content("scorecardLayout.html")
        emailContent={'mailContent':html_content}
        html_content = format_html_content(layout, emailContent)
        msg.attach(MIMEText(html_content, 'html'))
        # Connect to Gmail's SMTP server
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()  # Upgrade the connection to secure
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, recipient, msg.as_string())
    except Exception as e:
            print( jsonify({'error': str(e)}))
    return jsonify({'message': 'Email sent successfully with PDF attachment'})
def format_html_content(template, data):
    for key, value in data.items():
        placeholder = '{{' + key + '}}'
        template = template.replace(placeholder, str(value))
    return template



@app.route('/send-scorecard', methods=['POST'])
def sendScoreCardsemail():
    data=request.json
    pdf_filename="ScoreCard.pdf"
    competition_id=data['EventId']
    container = database.get_container_client("EventMeta")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    items = container.query_items(query=query, enable_cross_partition_query=True)
    metaData = list(items)
    metaData=metaData[0]
    container = database.get_container_client("EventTeamsJudges")
    query=f"SELECT *  FROM c WHERE c.EventId = '{competition_id}' "
    emailsData = list(container.query_items(query=query, enable_cross_partition_query=True))
    # Extract emails
    emails = []
    scorecard_container = database.get_container_client("EventScoreCard")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    scorecards = list(scorecard_container.query_items(query=query, enable_cross_partition_query=True))
    for entry in scorecards:
        subject="Score Card by "+entry['judgeName']+' for '+entry['category']
        entry['titleHeading']="Score Card For "+entry['category']
        entry['eventTitle']=metaData['eventTitle']
        for iteam in entry['scorecard']:
            entry[iteam]=entry['scorecard'][iteam]
        html_content = read_html_content("ScoreCard.html")
        formatted_html = format_html_content(html_content, entry)
        specific_team_id = entry['teamId']
        emails = []
        for event in emailsData:
            for team in event.get('teamsInfo', []):
                if team['teamName']['id'] == specific_team_id:
                    if team['teamRepresentativeEmail']['email']:
                        emails.append(team['teamRepresentativeEmail']['email'])
                    if team['coachName']['email']:
                        emails.append(team['coachName']['email'])
                    if team['DirectorName']['email']:
                        emails.append(team['DirectorName']['email'])
        createScoreCardPdf(entry['judgeName']+'_ScoreCard.pdf',entry)
        emails = list(filter(None, set(emails)))
        recipient = ', '.join(emails)
        recipient=recipient.split(",")
        for entry in recipient:
            try:
                # Create the email message
                msg = MIMEMultipart()
                msg['From'] = GMAIL_USER
                msg['To'] = entry
                msg['Subject'] = subject
                layout = read_html_content("scorecardLayout.html")
                emailContent={'mailContent':formatted_html}
                html_content = format_html_content(layout, emailContent)
                msg.attach(MIMEText(html_content, 'html'))

                with open(pdf_filename, 'rb') as pdf_file:
                    pdf_attachment = MIMEApplication(pdf_file.read(), _subtype='pdf')
                    pdf_attachment.add_header('Content-Disposition', 'attachment', filename=pdf_filename)
                    msg.attach(pdf_attachment)
                # Connect to Gmail's SMTP server
                with smtplib.SMTP('smtp.gmail.com', 587) as server:
                    server.starttls()  # Upgrade the connection to secure
                    server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                    server.sendmail(GMAIL_USER, recipient, msg.as_string())
            except Exception as e:
                return jsonify({'error': str(e)})
    return jsonify({'message': "success"})
def configureEventOrder(data):
    competition_id = data['EventId']
    scorecard_container = database.get_container_client("EventScoreCard")
    # Query scorecards for the given competition_id
    query = f"SELECT c.category, c.teamId, c.teamName FROM c WHERE c.EventId = @EventId"
    query_params = [{"name": "@EventId", "value": competition_id}]
    listPerformances = list(scorecard_container.query_items(
        query=query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))

    eventOrder_document = {
        "id": generate_unique_id(),
        "EventId": competition_id,
        "categoryOrder": []
    }

    seen = set()
    unique_listPerformances = []
    for performance in listPerformances:
        identifier = (performance['category'], performance['teamId'], performance['teamName'])
        if identifier not in seen:
            seen.add(identifier)
            unique_listPerformances.append(performance)

    # Organize performances by category
    categories = {}
    for performance in unique_listPerformances:
        category = performance.get("category")
        team_id = performance.get("teamId")
        team_name = performance.get("teamName")

        if category not in categories:
            categories[category] = []

        categories[category].append({
            "teamId": team_id,
            "teamName": team_name,
        })

    for category_index, (category, teams) in enumerate(categories.items(), start=1):
        eventOrder_document["categoryOrder"].append({
            "category": category,
            "order": category_index,
            "performances": []
        })

        for team_index, team in enumerate(teams, start=1):
            team_with_order = team.copy()
            team_with_order["order"] = team_index
            eventOrder_document["categoryOrder"][-1]["performances"].append(team_with_order)

    # Container for EventOrderConfig
    Ordercontainer = database.get_container_client("EventOrderConfig")
    
    try:
        # Check if the event order document already exists
        existing_documents = list(Ordercontainer.query_items(
            query="SELECT * FROM c WHERE c.EventId = @EventId",
            parameters=query_params,
            enable_cross_partition_query=True
        ))

        if existing_documents:
            # If exists, replace the document
            existing_document = existing_documents[0]
            updated_document = Ordercontainer.replace_item(item=existing_document['id'], body=eventOrder_document)
            return jsonify(updated_document), 200
        else:
            # If does not exist, create a new document
            eventOrder_document["CreationDateTimeStamp"]=datetime.now().isoformat()
            new_document = Ordercontainer.create_item(body=eventOrder_document)
            return jsonify(new_document), 201

    except exceptions.CosmosResourceNotFoundError:
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
def configureEventOrderMain(data):
    competition_id = data['EventId']
    container = database.get_container_client("EventTeamsJudges")
    meta_conatiner = database.get_container_client("EventMeta")
    # Query scorecards for the given competition_id
    query = f"SELECT c.teamsInfo FROM c WHERE c.EventId = @EventId"
    category_query=f"SELECT c.eventCategory FROM c WHERE c.EventId = @EventId"
    query_params = [{"name": "@EventId", "value": competition_id}]
    listCategory = list(meta_conatiner.query_items(
        query=category_query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))
    listPerformances = list(container.query_items(
        query=query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))

    eventOrder_document = {
        "id": generate_unique_id(),
        "EventId": competition_id,
        "categoryOrder": []
    }

    seen = set()
    unique_listPerformances = []
    for category in listCategory[0]['eventCategory']:
        for performance in listPerformances[0]['teamsInfo']:
            identifier = (category, performance['teamName']['id'], performance['teamName']['name'])
            data = {
            'category': category,
            'teamId': performance['teamName']['id'],
            'teamName': performance['teamName']['name']
            }
            if identifier not in seen:
                seen.add(identifier)
                unique_listPerformances.append(data)

    # Organize performances by category
    categories = {}
    for performance in unique_listPerformances:
        category = performance.get("category")
        team_id = performance.get("teamId")
        team_name = performance.get("teamName")

        if category not in categories:
            categories[category] = []

        categories[category].append({
            "teamId": team_id,
            "teamName": team_name,
        })

    for category_index, (category, teams) in enumerate(categories.items(), start=1):
        eventOrder_document["categoryOrder"].append({
            "category": category,
            "order": category_index,
            "performances": []
        })

        for team_index, team in enumerate(teams, start=1):
            team_with_order = team.copy()
            team_with_order["order"] = team_index
            eventOrder_document["categoryOrder"][-1]["performances"].append(team_with_order)

    # Container for EventOrderConfig
    Ordercontainer = database.get_container_client("EventOrderConfig")
    
    try:
        # Check if the event order document already exists
        existing_documents = list(Ordercontainer.query_items(
            query="SELECT * FROM c WHERE c.EventId = @EventId",
            parameters=query_params,
            enable_cross_partition_query=True
        ))

        if existing_documents:
            # If exists, replace the document
            existing_document = existing_documents[0]
            updated_document = Ordercontainer.replace_item(item=existing_document['id'], body=eventOrder_document)
            return jsonify(updated_document), 200
        else:
            # If does not exist, create a new document
            eventOrder_document["CreationDateTimeStamp"]=datetime.now().isoformat()
            new_document = Ordercontainer.create_item(body=eventOrder_document)
            return jsonify(new_document), 201

    except exceptions.CosmosResourceNotFoundError:
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500        
@app.route('/getEventOrder', methods=['POST'])
def getEventOrder():
    Ordercontainer = database.get_container_client("EventOrderConfig")
    data=request.json
    competition_id=data['EventId']
    try:
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
        eventOrder_document = list(Ordercontainer.query_items(query=query, enable_cross_partition_query=True))
        return  eventOrder_document[0], 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route('/updateEventOrder', methods=['POST'])
def updateEventOrder():
    Ordercontainer = database.get_container_client("EventOrderConfig")
    data=request.json
    competition_id=data['EventId']
    order_id=data['id']
    try:
        updated_document = Ordercontainer.replace_item(item=order_id, body=data)
        return  updated_document, 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
def createScoreCardPdf(filename,data):
    try:
        doc = SimpleDocTemplate(filename, pagesize=letter)
        styles = getSampleStyleSheet()
        elements = []

        # Title
        title_style = styles['Title']
        title_style.fontName = 'Helvetica-Bold'
        title_style.fontSize = 24
        title_style.alignment = TA_CENTER
        title = Paragraph("Score Card", title_style)
        elements.append(title)
        elements.append(Spacer(1, 0.5 * inch))

        for entry in data:
            # Event Title
            event_title_style = styles['Heading1']
            event_title_style.fontName = 'Helvetica-Bold'
            event_title_style.fontSize = 20
            event_title_style.alignment = TA_CENTER
            event_title = Paragraph(f"{entry['eventTitle']}", event_title_style)
            elements.append(event_title)
            elements.append(Spacer(1, 0.25 * inch))

            # Judge and Team Details
            details_style = styles['Normal']
            details_style.fontName = 'Helvetica'
            details_style.fontSize = 12
            details_style.alignment = TA_LEFT
            judge_name = Paragraph(f"<b>Judge:</b> {entry['judgeName']}", details_style)
            team_name = Paragraph(f"<b>Team:</b> {entry['teamName']}", details_style)
            comments = Paragraph(f"<b>Comments:</b> {entry['Comments']}", details_style)
            elements.append(judge_name)
            elements.append(team_name)
            elements.append(comments)
            elements.append(Spacer(1, 0.5 * inch))

            # Performance Table
            table_data = [
                ["Category", "Score"],
                ["Creativity", entry['creativity']],
                ["Difficulty", entry['difficulty']],
                ["Formation", entry['formation']],
                ["Sync", entry['sync']],
                ["Technique", entry['technique']],
                ["Total", entry['total']]
            ]

            table = Table(table_data, colWidths=[2.5 * inch, 1.5 * inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4CAF50')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 0.5 * inch))

        # Build PDF
        doc.build(elements)
    except Exception as e:
         print(jsonify({"error": str(e)}), 500)


def create_pdf(filename, data,eventOrder):
    doc = SimpleDocTemplate(filename, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    title = Paragraph("Event Schedule", styles['Title'])
    elements.append(title)
    elements.append(Paragraph("<br/>", styles['Normal']))

    # Event Title
    event_id = Paragraph(f"{data.get('eventTitle', '')}", styles['Normal'])
    elements.append(event_id)
    elements.append(Paragraph("<br/>", styles['Normal']))
    # Event Venue String
    event_id = Paragraph(f"Venue :{data.get('eventVenue', '')}", styles['Normal'])
    elements.append(event_id)
    elements.append(Paragraph("<br/>", styles['Normal']))
    # Event Data String
    event_id = Paragraph(f"Date and Time :{data.get('eventDateString', '')}", styles['Normal'])
    elements.append(event_id)
    elements.append(Paragraph("<br/>", styles['Normal']))

    # Categories and Performances
    for category in eventOrder['categoryOrder']:
        category_title = Paragraph(f"<b>Category: {category['category']} (Order: {category['order']})</b>", styles['Heading2'])
        elements.append(category_title)
        # Table Data
        table_data = [["Order", "Team Name"]]  # Removed "Team ID"
        for performance in category['performances']:
            table_data.append([performance['order'], performance['teamName']])  # Removed "Team ID"
        # Create Table
        table = Table(table_data, colWidths=[1 * inch, 2.5 * inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 1, black),
        ]))
        elements.append(table)
        elements.append(Paragraph("<br/>", styles['Normal']))

    # Build PDF
    doc.build(elements)

# Route to send email with PDF attachment
@app.route('/sendEventSchedule', methods=['POST'])
def send_email_with_pdf():
    data = request.json
    competition_id = data.get('EventId')
    # Initialize Cosmos Client
    container = database.get_container_client("EventMeta")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    items = container.query_items(query=query, enable_cross_partition_query=True)
    eventCategorys = list(items)
    data=eventCategorys[0]
    query=f"SELECT *  FROM c WHERE c.EventId = '{competition_id}' "
    subject = (data.get('eventTitle', '') + '|' +
           data.get('eventDateString', '') + '|' +
           data.get('eventVenue', '') + ' Schedule')    # Create the PDF
    Ordercontainer = database.get_container_client("EventOrderConfig")
    competition_id=data['EventId']
    container = database.get_container_client("EventTeamsJudges")
    emailsData = list(container.query_items(query=query, enable_cross_partition_query=True))
    # Extract emails
    emails = []

# Extract team representative, coach, and director emails
    for event in emailsData:
        for team in event.get('teamsInfo', []):
            if team['teamRepresentativeEmail']['email']:
                emails.append(team['teamRepresentativeEmail']['email'])
            if team['coachName']['email']:
                emails.append(team['coachName']['email'])
            if team['DirectorName']['email']:
                emails.append(team['DirectorName']['email'])
    # Remove empty strings (if any) and duplicates
    emails = list(filter(None, set(emails)))
    recipient = ','.join(emails)
    recipient=recipient.split(",")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    eventOrder_document = list(Ordercontainer.query_items(query=query, enable_cross_partition_query=True))
    #create_pdf(pdf_filename, data,eventOrder_document[0])
    # Read and format HTML content
    firsthtml = read_html_content("EventSchedule-converted.html")
    firsthtml=format_html_content(firsthtml, data)
    for category in eventOrder_document[0]['categoryOrder']:
        html_content = read_html_content("categoryEventTag.html")
        tagData={}
        tagData['Category']=category['category']
        # Table Data
        table_data = [["Order", "Team Name"]]  # Removed "Team ID"
        orderTags=''
        for performance in category['performances']:
            perData={}
            entryTag = read_html_content("orderandTeamTag.html")
            perData['order']=performance['order']
            perData['TeamName']=performance['teamName']
            orderTags=orderTags+format_html_content(entryTag, perData)
        tagData['orderTags']  = orderTags
        firsthtml = firsthtml+format_html_content(html_content, tagData)
    firsthtml=firsthtml+read_html_content("EventScheduleEnd.html")
    for entry in recipient:
        try:
            # Create the email message
            msg = MIMEMultipart()
            msg['From'] = GMAIL_USER
            msg['To'] = entry
            msg['Subject'] = subject
            layout = read_html_content("scorecardLayout.html")
            emailContent={'mailContent':firsthtml}
            html_content = format_html_content(layout, emailContent)
            msg.attach(MIMEText(html_content, 'html'))


            # Connect to Gmail's SMTP server
            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.starttls()  # Upgrade the connection to secure
                server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                server.sendmail(GMAIL_USER, recipient, msg.as_string())
            # Clean up
        except Exception as e:
            print( jsonify({'error': str(e)}))
    return jsonify({'message': 'Email sent successfully with PDF attachment'})
        
if __name__ == "__main__":
    app.run(host="0.0.0.0",port=5001)



@app.route('/getBanners', methods=['GET'])
def get_banner():
    try:
        # Get the container client inside the function
        container = database.get_container_client("BannerImgUrls")
        
        # Query to get all items from the container
        banners = list(container.read_all_items())
        
        # Return the data as JSON
        return jsonify(banners), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500      
@app.route('/removeBanner', methods=['POST'])
def remove_banner():
    try:
        # Get the container client
        container = database.get_container_client("BannerImgUrls")
        
        # Get the BannerId from the POST request body
        data = request.get_json()
        banner_id = data.get("BannerId")
        
        if not banner_id:
            return jsonify({"error": "BannerId is required"}), 400

        # Query to find the item based on the BannerId
        query = f"SELECT * FROM c WHERE c.BannerId = '{banner_id}'"
        items = list(container.query_items(query=query, enable_cross_partition_query=True))
        
        if not items:
            return jsonify({"error": "Banner not found"}), 404

        # Delete the item(s) based on BannerId
        for item in items:
            container.delete_item(item, partition_key=item['id'])

        return jsonify({"message": f"Banner with BannerId {banner_id} deleted successfully"}), 200
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
    
    # Ensure EventId is in the data
    if "EventId" not in data:
        return jsonify({"error": "EventId is required"}), 400
    data["id"] = generate_unique_id()
    data["status"] = "Scheduled"
    data["CreationDateTimeStamp"]= datetime.now().isoformat()
    container = database.get_container_client("EventMeta")
    # Query to check if a competition with the given EventId already exists
    query = "SELECT * FROM c WHERE c.EventId = @EventId"
    query_params = [
        {"name": "@EventId", "value": data["EventId"]}
    ]

    try:
        # Check if the competition already exists
        existing_items = list(container.query_items(
            query=query,
            parameters=query_params,
            enable_cross_partition_query=True
        ))
        if existing_items:
            # If the competition exists, replace it
            existing_item = existing_items[0]
            updated_item = container.replace_item(item=existing_item['id'], body=data)
            return jsonify({"eventId": data["EventId"]}), 200
        else:
            # If the competition does not exist, create a new one
            new_item = container.create_item(body=data)
            return jsonify({"eventId": data["EventId"]}), 201
    except exceptions.CosmosResourceNotFoundError:
        # Handle the case where the container or database does not exist
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        # Handle other Cosmos DB errors
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        # Handle any other exceptions
        return jsonify({"error": str(e)}), 500


@app.route('/updateTeams', methods=['POST'])
def createTeams():
    data = request.json
    # Ensure EventId is in the data
    if "EventId" not in data:
        return jsonify({"error": "EventId is required"}), 400
    # Generate a unique ID for the record (if necessary)
    data["id"] = generate_unique_id()
    data["CreationDateTimeStamp"]= datetime.now().isoformat()
    container = database.get_container_client("EventTeamsJudges")
    try:
        # Check if the record with the given EventId already exists
        query = "SELECT * FROM c WHERE c.EventId=@eventId"
        parameters = [{"name": "@eventId", "value": data["EventId"]}]
        existing_records = list(container.query_items(query=query, parameters=parameters, enable_cross_partition_query=True))
        if existing_records:
            # Record exists, update it
            existing_record = existing_records[0]
            # Update the existing record with new data
            container.replace_item(item=existing_record["id"], body=data)
            configureEventOrderMain(data) 
            return jsonify({"eventId": data["EventId"]}), 200
        else:
            # Record does not exist, create a new one
            container.create_item(body=data)
            configureEventOrderMain(data) 
            return jsonify({"eventId": data["EventId"]}), 201
    except exceptions.CosmosResourceNotFoundError:
        # Handle the case where the container or database does not exist
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        # Handle other Cosmos DB errors
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        # Handle any other exceptions
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
        
        # Define the scorecard access token document
        scorecardAccessTokens = {
            'id': generate_unique_id(),
            'EventId': data["EventId"],
            'judgeId': judge_id,
            'judgeName': judge_name,
            'HostAccess': False,
            'JudgeAccess': True,
            'CoachAccess': False,
            'TokenId': generate_token(),
            'CreationDateTimeStamp':datetime.now().isoformat()
        }

        # Query to check if token already exists for this judge and event
        query = "SELECT * FROM c WHERE c.EventId = @EventId AND c.judgeId = @judgeId"
        query_params = [
            {"name": "@EventId", "value": data["EventId"]},
            {"name": "@judgeId", "value": judge_id}
        ]

        try:
            # Check for existing tokens
            existing_tokens = list(accessTokenContainer.query_items(
                query=query,
                parameters=query_params,
                enable_cross_partition_query=True
            ))

            if existing_tokens:
                # If token exists, replace it
                existing_token = existing_tokens[0]
                scorecardAccessTokens['TokenId']=existing_token['TokenId']
                updated_token = accessTokenContainer.replace_item(item=existing_token['id'], body=scorecardAccessTokens)
                print(f"Updated access token for judge {judge_id}: {updated_token}")
            else:
                # If token does not exist, create a new one
                created_token = accessTokenContainer.create_item(body=scorecardAccessTokens)
                print(f"Created new access token for judge {judge_id}: {created_token}")
                
        except exceptions.CosmosHttpResponseError as e:
            # Log the error and continue; individual token creation or replacement failures should not stop the process
            print(f"Failed to process access token for judge {judge_id}: {e}")
        except Exception as e:
            # Handle unexpected errors
            print(f"Unexpected error for judge {judge_id}: {e}")


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
            'TokenId':generate_token(),
            'CreationDateTimeStamp':datetime.now().isoformat()
        }
        try: # Insert scorecard document into container
            accessTokenContainer.create_item(body=scorecardAccessTokens)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route('/CreateHostAccess', methods=['POST'])
def generateAccessTokensHostAccess():
    data=request.json
    HostConatiner = database.get_container_client("EventHostMeta")
    scorecardAccessTokens = {
        'id':generate_unique_id(),
        'HostId':generate_unique_id(),
        'Email':data['Email'],
        'CreationDateTimeStamp':datetime.now().isoformat()
    }
    accessTokenContainer = database.get_container_client("HostAccessRequests")
    try:
        # Insert scorecard document into container
        HostConatiner.create_item(body=scorecardAccessTokens)
        query = f"SELECT * FROM HostAccessRequests c WHERE c.Email = '{data['Email']}'"
        items = list(accessTokenContainer.query_items(query=query, enable_cross_partition_query=True))

        # If item(s) found, delete them
        for item in items:
            accessTokenContainer.delete_item(item=item['id'], partition_key=item['id'])
        
        return jsonify({"message": "Successfully Created Host Access"}), 200
        return jsonify({"message": "Successfully Created Host Access "}), 200
    except Exception as e:
        print("this is tyhe error"+e)
        return jsonify({"error": str(e)}), 500
import random
import string

def generate_code(length=6):
    characters = string.ascii_letters + string.digits
    code = ''.join(random.choice(characters) for _ in range(length))
    return code

# Example usage
print(generate_code(6))  # Generates a 6-character random code

CLIENT_ID = 'd7b1ed96-6e95-4354-af2a-544869f09e55'
CLIENT_SECRET = 'cfc8Q~2epL9FdAtlvwCEjwCmvrsJ-dDVKSj1Zclo'
TENANT_ID = 'eccdeba0-716d-4614-9824-ff4754cf84a9'
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["https://graph.microsoft.com/.default"]



# MSAL client instance
app_msal = ConfidentialClientApplication(
    CLIENT_ID,
    authority=AUTHORITY,
    client_credential=CLIENT_SECRET
)

GMAIL_USER = 'nandhasriramsabbina@gmail.com'
GMAIL_APP_PASSWORD = 'fngm ypaw glfo tgvo'

@app.route('/SentOtp', methods=['POST'])
def SentOtp():
    data = request.json
    emails = data['Email']
    recipient = emails
    subject = 'Email OTP Verification'
    html_content = read_html_content("emailInvite.html")
    otp = generate_code(6)
    
    # Save OTP to the database
    accessTokenContainer = database.get_container_client("OtpMeta")
    otpDoc = {
        'id': generate_unique_id(),
        'Email': data['Email'],
        'Otp': otp,
        'CreationDateTimeStamp': datetime.now().isoformat()
    }
    accessTokenContainer.create_item(body=otpDoc)
    
    # Format the email content with OTP
    html_content = format_html_content(html_content, otpDoc)
    layout = read_html_content("scorecardLayout.html")
    emailContent = {'mailContent': html_content}
    html_content = format_html_content(layout, emailContent)

    try:
        # Create the email message
        msg = MIMEMultipart()
        msg['From'] = GMAIL_USER
        msg['To'] = recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(html_content, 'html'))
        
        # Connect to Gmail's SMTP server
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()  # Upgrade the connection to secure
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, recipient, msg.as_string())
        
        return jsonify({'message': 'Email sent successfully'})
    except Exception as e:
        return jsonify({'error': str(e)})
    
@app.route('/OtpVerification', methods=['POST'])
def OtpVerification():
    data=request.json
    otpContainer = database.get_container_client("OtpMeta")
    try:
        validationQuery = f"SELECT * FROM c WHERE c.Email = '{data['Email']}' AND c.Otp = '{data['OTP_CODE']}'"
        Tokens = list(otpContainer.query_items(query=validationQuery, enable_cross_partition_query=True))
        if(len(Tokens)>0):
            result={'validation':'true'}
        else:
            result={'validation':'false'}
        return jsonify(result), 200
        # Insert scorecard document into container
    except Exception as e:
        return jsonify({"error": str(e)}), 500   
# Define the function to delete old OTP entries
# def delete_old_otps():
#     ten_minutes_ago = datetime.now() - timedelta(minutes=10)
#     query = "SELECT * FROM c WHERE c.CreationDateTimeStamp < @timestamp"
#     parameters = [{'name': '@timestamp', 'value': ten_minutes_ago.isoformat()}]
#     otpContainer = database.get_container_client("OtpMeta")
#     old_otps = otpContainer.query_items(query=query, parameters=parameters, enable_cross_partition_query=True)
#     for otp in old_otps:
#         otpContainer.delete_item(item=otp, partition_key=otp['id'])

# # Setup APScheduler to run the delete_old_otps function every minute
# scheduler = BackgroundScheduler()
# scheduler.add_job(delete_old_otps, 'interval', minutes=1)
# scheduler.start()     
@app.route('/createLoginDetails', methods=['POST'])
def createAccount():
    data=request.json
    accessTokenContainer = database.get_container_client("EventAuthKeys")
    scorecardAccessTokens = {
        'id':generate_unique_id(),
        'Email':data['Email'],
        'Password':data['Password'],
        'CreationDateTimeStamp':datetime.now().isoformat()
    }
    try:
        # Insert scorecard document into container
        accessTokenContainer.create_item(body=scorecardAccessTokens)
        if(data['HostAccessRequest']=='true'):
            RequestContainer = database.get_container_client("HostAccessRequests")
            RequestContainer.create_item(body=scorecardAccessTokens)
        return jsonify({"message": "Successfully Created Account "}), 200
    except Exception as e:
        print("this is tyhe error"+e)
        return jsonify({"error": str(e)}), 500

@app.route('/approveHostAccess', methods=['POST'])
def approveHostAccess():
    data=request.json
    result={}
    accessTokenContainer = database.get_container_client("HostAccessRequests")
    try:
        container = database.get_container_client("EventMeta")
        query = "SELECT * FROM c"
        items = accessTokenContainer.query_items(query=query, enable_cross_partition_query=True)
        result = list(items)
        return jsonify(result), 200
        # Insert scorecard document into container
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/authLoginDetails', methods=['POST'])
def authLoginDetails():
    data=request.json
    result={}
    accessTokenContainer = database.get_container_client("EventAuthKeys")
    try:
        validationQuery = f"SELECT * FROM c WHERE c.Email = '{data['Email']}' AND c.Password = '{data['Password']}'"
        Tokens = list(accessTokenContainer.query_items(query=validationQuery, enable_cross_partition_query=True))
        if(len(Tokens)>0):
            accessTokenContainer = database.get_container_client("EventHostMeta")
            validationQuery = f"SELECT * FROM c WHERE c.Email = '{data['Email']}'"
            access=list(accessTokenContainer.query_items(query=validationQuery, enable_cross_partition_query=True))
            if(len(access)>0):
                result={'validation':'true','HostAccess':'true','HostId':access[0]['HostId'],'OwnerAccess':'true' if data['Email'] == 'nandhashriramsabbina@outlook.com' else 'false'}
            else:
                result={'validation':'true','HostAccess':'false','OwnerAccess':'true' if data['Email'] == 'nandhashriramsabbina@outlook.com' else 'false'}    
        else:
            result={'validation':'false','HostAccess':'false','OwnerAccess':'true' if data['Email'] == 'nandhashriramsabbina@outlook.com' else 'false'}
        return jsonify(result), 200
        # Insert scorecard document into container
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
    
#saveScoreParameters   

@app.route('/saveScoreParameters', methods=['POST'])
def update_Scorecard():
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
    
@app.route('/getBanners', methods=['GET'])
def getBanners():
    try:
        container = database.get_container_client("BannerImgUrls")
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
    
def get_category_entry(scorecardMeta, category_name):
    return next((entry for entry in scorecardMeta if entry['category'] == category_name), None)

def add_scorecard(data):
    competition_id = data.get('EventId')

    # Initialize Cosmos Client
    container = database.get_container_client("EventMeta")
    query = f"SELECT c.eventCategory, c.scorecardMeta FROM c WHERE c.EventId = '{competition_id}'"

    try:
        # Fetch event category and scorecard meta
        items = container.query_items(query=query, enable_cross_partition_query=True)
        eventCategorys = list(items)
        if not eventCategorys:
            return jsonify({"error": "No event category found for the given EventId"}), 404

        eventCategorys = eventCategorys[0]
        eventScoreCardMeta = eventCategorys.get('scorecardMeta', [])
        eventCategorys = eventCategorys.get('eventCategory', [])

        # Initialize the scorecard container client
        scorecard_container = database.get_container_client("EventScoreCard")

        # Create scorecard entry for every judge * team combination
        for category in eventCategorys:
            for judge in data.get('JudegsInfo', []):
                judge_id = judge.get('id')
                judge_name = judge.get('name')
                for team in data.get('teamsInfo', []):
                    team_id = team.get('teamName', {}).get('id')
                    team_name = team.get('teamName', {}).get('name')

                    # Check for existing scorecard
                    unique_query = f"SELECT c.id FROM c WHERE c.EventId = '{data['EventId']}' AND c.judgeId = '{judge_id}' AND c.teamId = '{team_id}' AND c.category = '{category}'"
                    existing_entries = list(scorecard_container.query_items(query=unique_query, enable_cross_partition_query=True))

                    if existing_entries:
                        # Skip creating the entry if it already exists
                        continue

                    # Initialize scorecard with dynamic fields based on scorecardMeta
                    scorecard = {param['name']: 0 for param in get_category_entry(eventScoreCardMeta, category).get('parameters', [])}
                    scorecard['total'] = 0  # Initialize total score

                    # Create initial scorecard document
                    scorecard_document = {
                        'id': generate_unique_id(),
                        'EventId': data["EventId"],
                        'judgeId': judge_id,
                        'judgeName': judge_name,
                        'teamId': team_id,
                        'teamName': team_name,
                        'category': category,
                        'teamMemberId': None,  # Assuming we don't have specific team member ID here
                        'scorecard': scorecard,
                        'comments': '',
                        'CreationDateTimeStamp': datetime.now().isoformat()
                    }

                    # Insert scorecard document into container
                    try:
                        scorecard_container.create_item(body=scorecard_document)
                    except Exception as e:
                        return jsonify({"error": str(e)}), 500

        return jsonify({"status": "Scorecards created successfully"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/update_scores', methods=['POST'])
def update_scores():
    try:
        data = request.json
        scorecard_id=data["id"]
        eventId=data["EventId"]
        new_scores=data["scorecard"]
        comments=data["comment"]
        scorecard_container = database.get_container_client("EventScoreCard")
        # Retrieve the scorecard document from the database
        scorecard_document = scorecard_container.read_item(item=scorecard_id,partition_key=eventId)
        # Update the scores in the scorecard document
        scorecard_document['scorecard'].update(new_scores)
        scorecard_document['comments']=comments
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
        category=data.get('category')
        if not competition_id or not judge_id:
            return jsonify({"error": "Please provide both competitionId and judgeId in the request body"}), 400
        scorecard_container = database.get_container_client("EventScoreCard")
            # Query scorecards for the given competition_id and judge_id
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}' AND c.judgeId = '{judge_id}' AND c.teamId='{teamId}' AND c.category='{category}'"
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
        competition_id = data.get('EventId')

        # Initialize Cosmos DB container
        scorecard_container = database.get_container_client("EventScoreCard")
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
        scorecards = list(scorecard_container.query_items(query=query, enable_cross_partition_query=True))

        # Initialize dictionary to store scores per category
        category_scores = {}

        # Process each scorecard entry
        for scorecard in scorecards:
            team_id = scorecard.get('teamId')
            team_name = scorecard.get('teamName')
            category = scorecard.get('category')
            scorecard_data = scorecard.get('scorecard', {})

            # Compute score dynamically, excluding 'total'
            score_fields = [key for key in scorecard_data if key != 'total']
            score = sum(scorecard_data.get(field, 0) for field in score_fields)

            # Create a unique key for each team per category
            team_category_key = (team_name, category)

            if category not in category_scores:
                category_scores[category] = {}

            if team_category_key not in category_scores[category]:
                category_scores[category][team_category_key] = {
                    'teamId': team_id,
                    'teamName': team_name,
                    'category': category,
                    'total_score': 0
                }

            category_scores[category][team_category_key]['total_score'] += score

        # Prepare leaderboard sorted by categories and scores
        leaderboard = {}
        for category, scores in category_scores.items():
            sorted_scores = sorted(scores.values(), key=lambda x: x['total_score'], reverse=True)
            leaderboard[category] = sorted_scores

        return jsonify({"leaderboard": leaderboard}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


OUTLOOK_USER='nandhashriramsabbina@outlook.com'
OUTLOOK_PASSWORD='eakwnysdkybugfuh'  # Use App Password if 2-Step Verification is enabled
def read_html_content(file_path):
    with open(file_path, 'r') as file:
        return file.read()

@app.route('/send-email', methods=['POST'])
def send_email():
    data=request.json
    emails = data['emails']
    recipient = ', '.join(emails)
    recipient=recipient.split(",")
    subject = 'Test'
    html_content = read_html_content("emailInvite.html")
    formatted_html = format_html_content(html_content, entry)
    html_content.replace("PLACEHOLDER_COMPANY_NAME","Productions")
    html_content.replace("PLACEHOLDER_EVENT_TITLE","Productions")
    try:
        # Create the email message
        msg = MIMEMultipart()
        msg['From'] = GMAIL_USER
        msg['To'] = recipient
        msg['Subject'] = subject
        layout = read_html_content("scorecardLayout.html")
        emailContent={'mailContent':html_content}
        html_content = format_html_content(layout, emailContent)
        msg.attach(MIMEText(html_content, 'html'))
        # Connect to Gmail's SMTP server
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()  # Upgrade the connection to secure
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, recipient, msg.as_string())
    except Exception as e:
            print( jsonify({'error': str(e)}))
    return jsonify({'message': 'Email sent successfully with PDF attachment'})
def format_html_content(template, data):
    for key, value in data.items():
        placeholder = '{{' + key + '}}'
        template = template.replace(placeholder, str(value))
    return template



@app.route('/send-scorecard', methods=['POST'])
def sendScoreCardsemail():
    data=request.json
    pdf_filename="ScoreCard.pdf"
    competition_id=data['EventId']
    container = database.get_container_client("EventMeta")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    items = container.query_items(query=query, enable_cross_partition_query=True)
    metaData = list(items)
    metaData=metaData[0]
    container = database.get_container_client("EventTeamsJudges")
    query=f"SELECT *  FROM c WHERE c.EventId = '{competition_id}' "
    emailsData = list(container.query_items(query=query, enable_cross_partition_query=True))
    # Extract emails
    emails = []
    scorecard_container = database.get_container_client("EventScoreCard")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    scorecards = list(scorecard_container.query_items(query=query, enable_cross_partition_query=True))
    for entry in scorecards:
        subject="Score Card by "+entry['judgeName']+' for '+entry['category']
        entry['titleHeading']="Score Card For "+entry['category']
        entry['eventTitle']=metaData['eventTitle']
        for iteam in entry['scorecard']:
            entry[iteam]=entry['scorecard'][iteam]
        html_content = read_html_content("ScoreCard.html")
        formatted_html = format_html_content(html_content, entry)
        specific_team_id = entry['teamId']
        emails = []
        for event in emailsData:
            for team in event.get('teamsInfo', []):
                if team['teamName']['id'] == specific_team_id:
                    if team['teamRepresentativeEmail']['email']:
                        emails.append(team['teamRepresentativeEmail']['email'])
                    if team['coachName']['email']:
                        emails.append(team['coachName']['email'])
                    if team['DirectorName']['email']:
                        emails.append(team['DirectorName']['email'])
        createScoreCardPdf(entry['judgeName']+'_ScoreCard.pdf',entry)
        emails = list(filter(None, set(emails)))
        recipient = ', '.join(emails)
        recipient=recipient.split(",")
        for entry in recipient:
            try:
                # Create the email message
                msg = MIMEMultipart()
                msg['From'] = GMAIL_USER
                msg['To'] = entry
                msg['Subject'] = subject
                layout = read_html_content("scorecardLayout.html")
                emailContent={'mailContent':formatted_html}
                html_content = format_html_content(layout, emailContent)
                msg.attach(MIMEText(html_content, 'html'))

                with open(pdf_filename, 'rb') as pdf_file:
                    pdf_attachment = MIMEApplication(pdf_file.read(), _subtype='pdf')
                    pdf_attachment.add_header('Content-Disposition', 'attachment', filename=pdf_filename)
                    msg.attach(pdf_attachment)
                # Connect to Gmail's SMTP server
                with smtplib.SMTP('smtp.gmail.com', 587) as server:
                    server.starttls()  # Upgrade the connection to secure
                    server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                    server.sendmail(GMAIL_USER, recipient, msg.as_string())
            except Exception as e:
                return jsonify({'error': str(e)})
    return jsonify({'message': "success"})
def configureEventOrder(data):
    competition_id = data['EventId']
    scorecard_container = database.get_container_client("EventScoreCard")
    # Query scorecards for the given competition_id
    query = f"SELECT c.category, c.teamId, c.teamName FROM c WHERE c.EventId = @EventId"
    query_params = [{"name": "@EventId", "value": competition_id}]
    listPerformances = list(scorecard_container.query_items(
        query=query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))

    eventOrder_document = {
        "id": generate_unique_id(),
        "EventId": competition_id,
        "categoryOrder": []
    }

    seen = set()
    unique_listPerformances = []
    for performance in listPerformances:
        identifier = (performance['category'], performance['teamId'], performance['teamName'])
        if identifier not in seen:
            seen.add(identifier)
            unique_listPerformances.append(performance)

    # Organize performances by category
    categories = {}
    for performance in unique_listPerformances:
        category = performance.get("category")
        team_id = performance.get("teamId")
        team_name = performance.get("teamName")

        if category not in categories:
            categories[category] = []

        categories[category].append({
            "teamId": team_id,
            "teamName": team_name,
        })

    for category_index, (category, teams) in enumerate(categories.items(), start=1):
        eventOrder_document["categoryOrder"].append({
            "category": category,
            "order": category_index,
            "performances": []
        })

        for team_index, team in enumerate(teams, start=1):
            team_with_order = team.copy()
            team_with_order["order"] = team_index
            eventOrder_document["categoryOrder"][-1]["performances"].append(team_with_order)

    # Container for EventOrderConfig
    Ordercontainer = database.get_container_client("EventOrderConfig")
    
    try:
        # Check if the event order document already exists
        existing_documents = list(Ordercontainer.query_items(
            query="SELECT * FROM c WHERE c.EventId = @EventId",
            parameters=query_params,
            enable_cross_partition_query=True
        ))

        if existing_documents:
            # If exists, replace the document
            existing_document = existing_documents[0]
            updated_document = Ordercontainer.replace_item(item=existing_document['id'], body=eventOrder_document)
            return jsonify(updated_document), 200
        else:
            # If does not exist, create a new document
            eventOrder_document["CreationDateTimeStamp"]=datetime.now().isoformat()
            new_document = Ordercontainer.create_item(body=eventOrder_document)
            return jsonify(new_document), 201

    except exceptions.CosmosResourceNotFoundError:
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
def configureEventOrderMain(data):
    competition_id = data['EventId']
    container = database.get_container_client("EventTeamsJudges")
    meta_conatiner = database.get_container_client("EventMeta")
    # Query scorecards for the given competition_id
    query = f"SELECT c.teamsInfo FROM c WHERE c.EventId = @EventId"
    category_query=f"SELECT c.eventCategory FROM c WHERE c.EventId = @EventId"
    query_params = [{"name": "@EventId", "value": competition_id}]
    listCategory = list(meta_conatiner.query_items(
        query=category_query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))
    listPerformances = list(container.query_items(
        query=query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))

    eventOrder_document = {
        "id": generate_unique_id(),
        "EventId": competition_id,
        "categoryOrder": []
    }

    seen = set()
    unique_listPerformances = []
    for category in listCategory[0]['eventCategory']:
        for performance in listPerformances[0]['teamsInfo']:
            identifier = (category, performance['teamName']['id'], performance['teamName']['name'])
            data = {
            'category': category,
            'teamId': performance['teamName']['id'],
            'teamName': performance['teamName']['name']
            }
            if identifier not in seen:
                seen.add(identifier)
                unique_listPerformances.append(data)

    # Organize performances by category
    categories = {}
    for performance in unique_listPerformances:
        category = performance.get("category")
        team_id = performance.get("teamId")
        team_name = performance.get("teamName")

        if category not in categories:
            categories[category] = []

        categories[category].append({
            "teamId": team_id,
            "teamName": team_name,
        })

    for category_index, (category, teams) in enumerate(categories.items(), start=1):
        eventOrder_document["categoryOrder"].append({
            "category": category,
            "order": category_index,
            "performances": []
        })

        for team_index, team in enumerate(teams, start=1):
            team_with_order = team.copy()
            team_with_order["order"] = team_index
            eventOrder_document["categoryOrder"][-1]["performances"].append(team_with_order)

    # Container for EventOrderConfig
    Ordercontainer = database.get_container_client("EventOrderConfig")
    
    try:
        # Check if the event order document already exists
        existing_documents = list(Ordercontainer.query_items(
            query="SELECT * FROM c WHERE c.EventId = @EventId",
            parameters=query_params,
            enable_cross_partition_query=True
        ))

        if existing_documents:
            # If exists, replace the document
            existing_document = existing_documents[0]
            updated_document = Ordercontainer.replace_item(item=existing_document['id'], body=eventOrder_document)
            return jsonify(updated_document), 200
        else:
            # If does not exist, create a new document
            eventOrder_document["CreationDateTimeStamp"]=datetime.now().isoformat()
            new_document = Ordercontainer.create_item(body=eventOrder_document)
            return jsonify(new_document), 201

    except exceptions.CosmosResourceNotFoundError:
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500        
@app.route('/getEventOrder', methods=['POST'])
def getEventOrder():
    Ordercontainer = database.get_container_client("EventOrderConfig")
    data=request.json
    competition_id=data['EventId']
    try:
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
        eventOrder_document = list(Ordercontainer.query_items(query=query, enable_cross_partition_query=True))
        return  eventOrder_document[0], 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route('/updateEventOrder', methods=['POST'])
def updateEventOrder():
    Ordercontainer = database.get_container_client("EventOrderConfig")
    data=request.json
    competition_id=data['EventId']
    order_id=data['id']
    try:
        updated_document = Ordercontainer.replace_item(item=order_id, body=data)
        return  updated_document, 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
def createScoreCardPdf(filename,data):
    try:
        doc = SimpleDocTemplate(filename, pagesize=letter)
        styles = getSampleStyleSheet()
        elements = []

        # Title
        title_style = styles['Title']
        title_style.fontName = 'Helvetica-Bold'
        title_style.fontSize = 24
        title_style.alignment = TA_CENTER
        title = Paragraph("Score Card", title_style)
        elements.append(title)
        elements.append(Spacer(1, 0.5 * inch))

        for entry in data:
            # Event Title
            event_title_style = styles['Heading1']
            event_title_style.fontName = 'Helvetica-Bold'
            event_title_style.fontSize = 20
            event_title_style.alignment = TA_CENTER
            event_title = Paragraph(f"{entry['eventTitle']}", event_title_style)
            elements.append(event_title)
            elements.append(Spacer(1, 0.25 * inch))

            # Judge and Team Details
            details_style = styles['Normal']
            details_style.fontName = 'Helvetica'
            details_style.fontSize = 12
            details_style.alignment = TA_LEFT
            judge_name = Paragraph(f"<b>Judge:</b> {entry['judgeName']}", details_style)
            team_name = Paragraph(f"<b>Team:</b> {entry['teamName']}", details_style)
            comments = Paragraph(f"<b>Comments:</b> {entry['Comments']}", details_style)
            elements.append(judge_name)
            elements.append(team_name)
            elements.append(comments)
            elements.append(Spacer(1, 0.5 * inch))

            # Performance Table
            table_data = [
                ["Category", "Score"],
                ["Creativity", entry['creativity']],
                ["Difficulty", entry['difficulty']],
                ["Formation", entry['formation']],
                ["Sync", entry['sync']],
                ["Technique", entry['technique']],
                ["Total", entry['total']]
            ]

            table = Table(table_data, colWidths=[2.5 * inch, 1.5 * inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4CAF50')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 0.5 * inch))

        # Build PDF
        doc.build(elements)
    except Exception as e:
         print(jsonify({"error": str(e)}), 500)


def create_pdf(filename, data,eventOrder):
    doc = SimpleDocTemplate(filename, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    title = Paragraph("Event Schedule", styles['Title'])
    elements.append(title)
    elements.append(Paragraph("<br/>", styles['Normal']))

    # Event Title
    event_id = Paragraph(f"{data.get('eventTitle', '')}", styles['Normal'])
    elements.append(event_id)
    elements.append(Paragraph("<br/>", styles['Normal']))
    # Event Venue String
    event_id = Paragraph(f"Venue :{data.get('eventVenue', '')}", styles['Normal'])
    elements.append(event_id)
    elements.append(Paragraph("<br/>", styles['Normal']))
    # Event Data String
    event_id = Paragraph(f"Date and Time :{data.get('eventDateString', '')}", styles['Normal'])
    elements.append(event_id)
    elements.append(Paragraph("<br/>", styles['Normal']))

    # Categories and Performances
    for category in eventOrder['categoryOrder']:
        category_title = Paragraph(f"<b>Category: {category['category']} (Order: {category['order']})</b>", styles['Heading2'])
        elements.append(category_title)
        # Table Data
        table_data = [["Order", "Team Name"]]  # Removed "Team ID"
        for performance in category['performances']:
            table_data.append([performance['order'], performance['teamName']])  # Removed "Team ID"
        # Create Table
        table = Table(table_data, colWidths=[1 * inch, 2.5 * inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 1, black),
        ]))
        elements.append(table)
        elements.append(Paragraph("<br/>", styles['Normal']))

    # Build PDF
    doc.build(elements)

# Route to send email with PDF attachment
@app.route('/sendEventSchedule', methods=['POST'])
def send_email_with_pdf():
    data = request.json
    competition_id = data.get('EventId')
    # Initialize Cosmos Client
    container = database.get_container_client("EventMeta")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    items = container.query_items(query=query, enable_cross_partition_query=True)
    eventCategorys = list(items)
    data=eventCategorys[0]
    query=f"SELECT *  FROM c WHERE c.EventId = '{competition_id}' "
    subject = (data.get('eventTitle', '') + '|' +
           data.get('eventDateString', '') + '|' +
           data.get('eventVenue', '') + ' Schedule')    # Create the PDF
    Ordercontainer = database.get_container_client("EventOrderConfig")
    competition_id=data['EventId']
    container = database.get_container_client("EventTeamsJudges")
    emailsData = list(container.query_items(query=query, enable_cross_partition_query=True))
    # Extract emails
    emails = []

# Extract team representative, coach, and director emails
    for event in emailsData:
        for team in event.get('teamsInfo', []):
            if team['teamRepresentativeEmail']['email']:
                emails.append(team['teamRepresentativeEmail']['email'])
            if team['coachName']['email']:
                emails.append(team['coachName']['email'])
            if team['DirectorName']['email']:
                emails.append(team['DirectorName']['email'])
    # Remove empty strings (if any) and duplicates
    emails = list(filter(None, set(emails)))
    recipient = ','.join(emails)
    recipient=recipient.split(",")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    eventOrder_document = list(Ordercontainer.query_items(query=query, enable_cross_partition_query=True))
    #create_pdf(pdf_filename, data,eventOrder_document[0])
    # Read and format HTML content
    firsthtml = read_html_content("EventSchedule-converted.html")
    firsthtml=format_html_content(firsthtml, data)
    for category in eventOrder_document[0]['categoryOrder']:
        html_content = read_html_content("categoryEventTag.html")
        tagData={}
        tagData['Category']=category['category']
        # Table Data
        table_data = [["Order", "Team Name"]]  # Removed "Team ID"
        orderTags=''
        for performance in category['performances']:
            perData={}
            entryTag = read_html_content("orderandTeamTag.html")
            perData['order']=performance['order']
            perData['TeamName']=performance['teamName']
            orderTags=orderTags+format_html_content(entryTag, perData)
        tagData['orderTags']  = orderTags
        firsthtml = firsthtml+format_html_content(html_content, tagData)
    firsthtml=firsthtml+read_html_content("EventScheduleEnd.html")
    for entry in recipient:
        try:
            # Create the email message
            msg = MIMEMultipart()
            msg['From'] = GMAIL_USER
            msg['To'] = entry
            msg['Subject'] = subject
            layout = read_html_content("scorecardLayout.html")
            emailContent={'mailContent':firsthtml}
            html_content = format_html_content(layout, emailContent)
            msg.attach(MIMEText(html_content, 'html'))


            # Connect to Gmail's SMTP server
            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.starttls()  # Upgrade the connection to secure
                server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                server.sendmail(GMAIL_USER, recipient, msg.as_string())
            # Clean up
        except Exception as e:
            print( jsonify({'error': str(e)}))
    return jsonify({'message': 'Email sent successfully with PDF attachment'})
        
if __name__ == "__main__":
    app.run(host="0.0.0.0",port=5001)



@app.route('/getBanners', methods=['GET'])
def get_banner():
    try:
        # Get the container client inside the function
        container = database.get_container_client("BannerImgUrls")
        
        # Query to get all items from the container
        banners = list(container.read_all_items())
        
        # Return the data as JSON
        return jsonify(banners), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500      
@app.route('/removeBanner', methods=['POST'])
def remove_banner():
    try:
        # Get the container client
        container = database.get_container_client("BannerImgUrls")
        
        # Get the BannerId from the POST request body
        data = request.get_json()
        banner_id = data.get("BannerId")
        
        if not banner_id:
            return jsonify({"error": "BannerId is required"}), 400

        # Query to find the item based on the BannerId
        query = f"SELECT * FROM c WHERE c.BannerId = '{banner_id}'"
        items = list(container.query_items(query=query, enable_cross_partition_query=True))
        
        if not items:
            return jsonify({"error": "Banner not found"}), 404

        # Delete the item(s) based on BannerId
        for item in items:
            container.delete_item(item, partition_key=item['id'])

        return jsonify({"message": f"Banner with BannerId {banner_id} deleted successfully"}), 200
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
    
    # Ensure EventId is in the data
    if "EventId" not in data:
        return jsonify({"error": "EventId is required"}), 400
    data["id"] = generate_unique_id()
    data["status"] = "Scheduled"
    data["CreationDateTimeStamp"]= datetime.now().isoformat()
    container = database.get_container_client("EventMeta")
    # Query to check if a competition with the given EventId already exists
    query = "SELECT * FROM c WHERE c.EventId = @EventId"
    query_params = [
        {"name": "@EventId", "value": data["EventId"]}
    ]

    try:
        # Check if the competition already exists
        existing_items = list(container.query_items(
            query=query,
            parameters=query_params,
            enable_cross_partition_query=True
        ))
        if existing_items:
            # If the competition exists, replace it
            existing_item = existing_items[0]
            updated_item = container.replace_item(item=existing_item['id'], body=data)
            return jsonify({"eventId": data["EventId"]}), 200
        else:
            # If the competition does not exist, create a new one
            new_item = container.create_item(body=data)
            return jsonify({"eventId": data["EventId"]}), 201
    except exceptions.CosmosResourceNotFoundError:
        # Handle the case where the container or database does not exist
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        # Handle other Cosmos DB errors
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        # Handle any other exceptions
        return jsonify({"error": str(e)}), 500


@app.route('/updateTeams', methods=['POST'])
def createTeams():
    data = request.json
    # Ensure EventId is in the data
    if "EventId" not in data:
        return jsonify({"error": "EventId is required"}), 400
    # Generate a unique ID for the record (if necessary)
    data["id"] = generate_unique_id()
    data["CreationDateTimeStamp"]= datetime.now().isoformat()
    container = database.get_container_client("EventTeamsJudges")
    try:
        # Check if the record with the given EventId already exists
        query = "SELECT * FROM c WHERE c.EventId=@eventId"
        parameters = [{"name": "@eventId", "value": data["EventId"]}]
        existing_records = list(container.query_items(query=query, parameters=parameters, enable_cross_partition_query=True))
        if existing_records:
            # Record exists, update it
            existing_record = existing_records[0]
            # Update the existing record with new data
            container.replace_item(item=existing_record["id"], body=data)
            configureEventOrderMain(data) 
            return jsonify({"eventId": data["EventId"]}), 200
        else:
            # Record does not exist, create a new one
            container.create_item(body=data)
            configureEventOrderMain(data) 
            return jsonify({"eventId": data["EventId"]}), 201
    except exceptions.CosmosResourceNotFoundError:
        # Handle the case where the container or database does not exist
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        # Handle other Cosmos DB errors
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        # Handle any other exceptions
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
        
        # Define the scorecard access token document
        scorecardAccessTokens = {
            'id': generate_unique_id(),
            'EventId': data["EventId"],
            'judgeId': judge_id,
            'judgeName': judge_name,
            'HostAccess': False,
            'JudgeAccess': True,
            'CoachAccess': False,
            'TokenId': generate_token(),
            'CreationDateTimeStamp':datetime.now().isoformat()
        }

        # Query to check if token already exists for this judge and event
        query = "SELECT * FROM c WHERE c.EventId = @EventId AND c.judgeId = @judgeId"
        query_params = [
            {"name": "@EventId", "value": data["EventId"]},
            {"name": "@judgeId", "value": judge_id}
        ]

        try:
            # Check for existing tokens
            existing_tokens = list(accessTokenContainer.query_items(
                query=query,
                parameters=query_params,
                enable_cross_partition_query=True
            ))

            if existing_tokens:
                # If token exists, replace it
                existing_token = existing_tokens[0]
                scorecardAccessTokens['TokenId']=existing_token['TokenId']
                updated_token = accessTokenContainer.replace_item(item=existing_token['id'], body=scorecardAccessTokens)
                print(f"Updated access token for judge {judge_id}: {updated_token}")
            else:
                # If token does not exist, create a new one
                created_token = accessTokenContainer.create_item(body=scorecardAccessTokens)
                print(f"Created new access token for judge {judge_id}: {created_token}")
                
        except exceptions.CosmosHttpResponseError as e:
            # Log the error and continue; individual token creation or replacement failures should not stop the process
            print(f"Failed to process access token for judge {judge_id}: {e}")
        except Exception as e:
            # Handle unexpected errors
            print(f"Unexpected error for judge {judge_id}: {e}")


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
            'TokenId':generate_token(),
            'CreationDateTimeStamp':datetime.now().isoformat()
        }
        try: # Insert scorecard document into container
            accessTokenContainer.create_item(body=scorecardAccessTokens)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route('/CreateHostAccess', methods=['POST'])
def generateAccessTokensHostAccess():
    data=request.json
    HostConatiner = database.get_container_client("EventHostMeta")
    scorecardAccessTokens = {
        'id':generate_unique_id(),
        'HostId':generate_unique_id(),
        'Email':data['Email'],
        'CreationDateTimeStamp':datetime.now().isoformat()
    }
    accessTokenContainer = database.get_container_client("HostAccessRequests")
    try:
        # Insert scorecard document into container
        HostConatiner.create_item(body=scorecardAccessTokens)
        query = f"SELECT * FROM HostAccessRequests c WHERE c.Email = '{data['Email']}'"
        items = list(accessTokenContainer.query_items(query=query, enable_cross_partition_query=True))

        # If item(s) found, delete them
        for item in items:
            accessTokenContainer.delete_item(item=item['id'], partition_key=item['id'])
        
        return jsonify({"message": "Successfully Created Host Access"}), 200
        return jsonify({"message": "Successfully Created Host Access "}), 200
    except Exception as e:
        print("this is tyhe error"+e)
        return jsonify({"error": str(e)}), 500
import random
import string

def generate_code(length=6):
    characters = string.ascii_letters + string.digits
    code = ''.join(random.choice(characters) for _ in range(length))
    return code

# Example usage
print(generate_code(6))  # Generates a 6-character random code

CLIENT_ID = 'd7b1ed96-6e95-4354-af2a-544869f09e55'
CLIENT_SECRET = 'cfc8Q~2epL9FdAtlvwCEjwCmvrsJ-dDVKSj1Zclo'
TENANT_ID = 'eccdeba0-716d-4614-9824-ff4754cf84a9'
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["https://graph.microsoft.com/.default"]



# MSAL client instance
app_msal = ConfidentialClientApplication(
    CLIENT_ID,
    authority=AUTHORITY,
    client_credential=CLIENT_SECRET
)

GMAIL_USER = 'nandhasriramsabbina@gmail.com'
GMAIL_APP_PASSWORD = 'fngm ypaw glfo tgvo'

@app.route('/SentOtp', methods=['POST'])
def SentOtp():
    data = request.json
    emails = data['Email']
    recipient = emails
    subject = 'Email OTP Verification'
    html_content = read_html_content("emailInvite.html")
    otp = generate_code(6)
    
    # Save OTP to the database
    accessTokenContainer = database.get_container_client("OtpMeta")
    otpDoc = {
        'id': generate_unique_id(),
        'Email': data['Email'],
        'Otp': otp,
        'CreationDateTimeStamp': datetime.now().isoformat()
    }
    accessTokenContainer.create_item(body=otpDoc)
    
    # Format the email content with OTP
    html_content = format_html_content(html_content, otpDoc)
    layout = read_html_content("scorecardLayout.html")
    emailContent = {'mailContent': html_content}
    html_content = format_html_content(layout, emailContent)

    try:
        # Create the email message
        msg = MIMEMultipart()
        msg['From'] = GMAIL_USER
        msg['To'] = recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(html_content, 'html'))
        
        # Connect to Gmail's SMTP server
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()  # Upgrade the connection to secure
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, recipient, msg.as_string())
        
        return jsonify({'message': 'Email sent successfully'})
    except Exception as e:
        return jsonify({'error': str(e)})
    
@app.route('/OtpVerification', methods=['POST'])
def OtpVerification():
    data=request.json
    otpContainer = database.get_container_client("OtpMeta")
    try:
        validationQuery = f"SELECT * FROM c WHERE c.Email = '{data['Email']}' AND c.Otp = '{data['OTP_CODE']}'"
        Tokens = list(otpContainer.query_items(query=validationQuery, enable_cross_partition_query=True))
        if(len(Tokens)>0):
            result={'validation':'true'}
        else:
            result={'validation':'false'}
        return jsonify(result), 200
        # Insert scorecard document into container
    except Exception as e:
        return jsonify({"error": str(e)}), 500   
# Define the function to delete old OTP entries
# def delete_old_otps():
#     ten_minutes_ago = datetime.now() - timedelta(minutes=10)
#     query = "SELECT * FROM c WHERE c.CreationDateTimeStamp < @timestamp"
#     parameters = [{'name': '@timestamp', 'value': ten_minutes_ago.isoformat()}]
#     otpContainer = database.get_container_client("OtpMeta")
#     old_otps = otpContainer.query_items(query=query, parameters=parameters, enable_cross_partition_query=True)
#     for otp in old_otps:
#         otpContainer.delete_item(item=otp, partition_key=otp['id'])

# # Setup APScheduler to run the delete_old_otps function every minute
# scheduler = BackgroundScheduler()
# scheduler.add_job(delete_old_otps, 'interval', minutes=1)
# scheduler.start()     
@app.route('/createLoginDetails', methods=['POST'])
def createAccount():
    data=request.json
    accessTokenContainer = database.get_container_client("EventAuthKeys")
    scorecardAccessTokens = {
        'id':generate_unique_id(),
        'Email':data['Email'],
        'Password':data['Password'],
        'CreationDateTimeStamp':datetime.now().isoformat()
    }
    try:
        # Insert scorecard document into container
        accessTokenContainer.create_item(body=scorecardAccessTokens)
        if(data['HostAccessRequest']=='true'):
            RequestContainer = database.get_container_client("HostAccessRequests")
            RequestContainer.create_item(body=scorecardAccessTokens)
        return jsonify({"message": "Successfully Created Account "}), 200
    except Exception as e:
        print("this is tyhe error"+e)
        return jsonify({"error": str(e)}), 500

@app.route('/approveHostAccess', methods=['POST'])
def approveHostAccess():
    data=request.json
    result={}
    accessTokenContainer = database.get_container_client("HostAccessRequests")
    try:
        container = database.get_container_client("EventMeta")
        query = "SELECT * FROM c"
        items = accessTokenContainer.query_items(query=query, enable_cross_partition_query=True)
        result = list(items)
        return jsonify(result), 200
        # Insert scorecard document into container
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/authLoginDetails', methods=['POST'])
def authLoginDetails():
    data=request.json
    result={}
    accessTokenContainer = database.get_container_client("EventAuthKeys")
    try:
        validationQuery = f"SELECT * FROM c WHERE c.Email = '{data['Email']}' AND c.Password = '{data['Password']}'"
        Tokens = list(accessTokenContainer.query_items(query=validationQuery, enable_cross_partition_query=True))
        if(len(Tokens)>0):
            accessTokenContainer = database.get_container_client("EventHostMeta")
            validationQuery = f"SELECT * FROM c WHERE c.Email = '{data['Email']}'"
            access=list(accessTokenContainer.query_items(query=validationQuery, enable_cross_partition_query=True))
            if(len(access)>0):
                result={'validation':'true','HostAccess':'true','HostId':access[0]['HostId'],'OwnerAccess':'true' if data['Email'] == 'nandhashriramsabbina@outlook.com' else 'false'}
            else:
                result={'validation':'true','HostAccess':'false','OwnerAccess':'true' if data['Email'] == 'nandhashriramsabbina@outlook.com' else 'false'}    
        else:
            result={'validation':'false','HostAccess':'false','OwnerAccess':'true' if data['Email'] == 'nandhashriramsabbina@outlook.com' else 'false'}
        return jsonify(result), 200
        # Insert scorecard document into container
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
    
#saveScoreParameters   

@app.route('/saveScoreParameters', methods=['POST'])
def update_Scorecard():
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
    
@app.route('/getBanners', methods=['GET'])
def getBanners():
    try:
        container = database.get_container_client("BannerImgUrls")
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
    
def get_category_entry(scorecardMeta, category_name):
    return next((entry for entry in scorecardMeta if entry['category'] == category_name), None)

def add_scorecard(data):
    competition_id = data.get('EventId')

    # Initialize Cosmos Client
    container = database.get_container_client("EventMeta")
    query = f"SELECT c.eventCategory, c.scorecardMeta FROM c WHERE c.EventId = '{competition_id}'"

    try:
        # Fetch event category and scorecard meta
        items = container.query_items(query=query, enable_cross_partition_query=True)
        eventCategorys = list(items)
        if not eventCategorys:
            return jsonify({"error": "No event category found for the given EventId"}), 404

        eventCategorys = eventCategorys[0]
        eventScoreCardMeta = eventCategorys.get('scorecardMeta', [])
        eventCategorys = eventCategorys.get('eventCategory', [])

        # Initialize the scorecard container client
        scorecard_container = database.get_container_client("EventScoreCard")

        # Create scorecard entry for every judge * team combination
        for category in eventCategorys:
            for judge in data.get('JudegsInfo', []):
                judge_id = judge.get('id')
                judge_name = judge.get('name')
                for team in data.get('teamsInfo', []):
                    team_id = team.get('teamName', {}).get('id')
                    team_name = team.get('teamName', {}).get('name')

                    # Check for existing scorecard
                    unique_query = f"SELECT c.id FROM c WHERE c.EventId = '{data['EventId']}' AND c.judgeId = '{judge_id}' AND c.teamId = '{team_id}' AND c.category = '{category}'"
                    existing_entries = list(scorecard_container.query_items(query=unique_query, enable_cross_partition_query=True))

                    if existing_entries:
                        # Skip creating the entry if it already exists
                        continue

                    # Initialize scorecard with dynamic fields based on scorecardMeta
                    scorecard = {param['name']: 0 for param in get_category_entry(eventScoreCardMeta, category).get('parameters', [])}
                    scorecard['total'] = 0  # Initialize total score

                    # Create initial scorecard document
                    scorecard_document = {
                        'id': generate_unique_id(),
                        'EventId': data["EventId"],
                        'judgeId': judge_id,
                        'judgeName': judge_name,
                        'teamId': team_id,
                        'teamName': team_name,
                        'category': category,
                        'teamMemberId': None,  # Assuming we don't have specific team member ID here
                        'scorecard': scorecard,
                        'comments': '',
                        'CreationDateTimeStamp': datetime.now().isoformat()
                    }

                    # Insert scorecard document into container
                    try:
                        scorecard_container.create_item(body=scorecard_document)
                    except Exception as e:
                        return jsonify({"error": str(e)}), 500

        return jsonify({"status": "Scorecards created successfully"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/update_scores', methods=['POST'])
def update_scores():
    try:
        data = request.json
        scorecard_id=data["id"]
        eventId=data["EventId"]
        new_scores=data["scorecard"]
        comments=data["comment"]
        scorecard_container = database.get_container_client("EventScoreCard")
        # Retrieve the scorecard document from the database
        scorecard_document = scorecard_container.read_item(item=scorecard_id,partition_key=eventId)
        # Update the scores in the scorecard document
        scorecard_document['scorecard'].update(new_scores)
        scorecard_document['comments']=comments
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
        category=data.get('category')
        if not competition_id or not judge_id:
            return jsonify({"error": "Please provide both competitionId and judgeId in the request body"}), 400
        scorecard_container = database.get_container_client("EventScoreCard")
            # Query scorecards for the given competition_id and judge_id
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}' AND c.judgeId = '{judge_id}' AND c.teamId='{teamId}' AND c.category='{category}'"
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
        competition_id = data.get('EventId')

        # Initialize Cosmos DB container
        scorecard_container = database.get_container_client("EventScoreCard")
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
        scorecards = list(scorecard_container.query_items(query=query, enable_cross_partition_query=True))

        # Initialize dictionary to store scores per category
        category_scores = {}

        # Process each scorecard entry
        for scorecard in scorecards:
            team_id = scorecard.get('teamId')
            team_name = scorecard.get('teamName')
            category = scorecard.get('category')
            scorecard_data = scorecard.get('scorecard', {})

            # Compute score dynamically, excluding 'total'
            score_fields = [key for key in scorecard_data if key != 'total']
            score = sum(scorecard_data.get(field, 0) for field in score_fields)

            # Create a unique key for each team per category
            team_category_key = (team_name, category)

            if category not in category_scores:
                category_scores[category] = {}

            if team_category_key not in category_scores[category]:
                category_scores[category][team_category_key] = {
                    'teamId': team_id,
                    'teamName': team_name,
                    'category': category,
                    'total_score': 0
                }

            category_scores[category][team_category_key]['total_score'] += score

        # Prepare leaderboard sorted by categories and scores
        leaderboard = {}
        for category, scores in category_scores.items():
            sorted_scores = sorted(scores.values(), key=lambda x: x['total_score'], reverse=True)
            leaderboard[category] = sorted_scores

        return jsonify({"leaderboard": leaderboard}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


OUTLOOK_USER='nandhashriramsabbina@outlook.com'
OUTLOOK_PASSWORD='eakwnysdkybugfuh'  # Use App Password if 2-Step Verification is enabled
def read_html_content(file_path):
    with open(file_path, 'r') as file:
        return file.read()

@app.route('/send-email', methods=['POST'])
def send_email():
    data=request.json
    emails = data['emails']
    recipient = ', '.join(emails)
    recipient=recipient.split(",")
    subject = 'Test'
    html_content = read_html_content("emailInvite.html")
    formatted_html = format_html_content(html_content, entry)
    html_content.replace("PLACEHOLDER_COMPANY_NAME","Productions")
    html_content.replace("PLACEHOLDER_EVENT_TITLE","Productions")
    try:
        # Create the email message
        msg = MIMEMultipart()
        msg['From'] = GMAIL_USER
        msg['To'] = recipient
        msg['Subject'] = subject
        layout = read_html_content("scorecardLayout.html")
        emailContent={'mailContent':html_content}
        html_content = format_html_content(layout, emailContent)
        msg.attach(MIMEText(html_content, 'html'))
        # Connect to Gmail's SMTP server
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()  # Upgrade the connection to secure
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, recipient, msg.as_string())
    except Exception as e:
            print( jsonify({'error': str(e)}))
    return jsonify({'message': 'Email sent successfully with PDF attachment'})
def format_html_content(template, data):
    for key, value in data.items():
        placeholder = '{{' + key + '}}'
        template = template.replace(placeholder, str(value))
    return template



@app.route('/send-scorecard', methods=['POST'])
def sendScoreCardsemail():
    data=request.json
    pdf_filename="ScoreCard.pdf"
    competition_id=data['EventId']
    container = database.get_container_client("EventMeta")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    items = container.query_items(query=query, enable_cross_partition_query=True)
    metaData = list(items)
    metaData=metaData[0]
    container = database.get_container_client("EventTeamsJudges")
    query=f"SELECT *  FROM c WHERE c.EventId = '{competition_id}' "
    emailsData = list(container.query_items(query=query, enable_cross_partition_query=True))
    # Extract emails
    emails = []
    scorecard_container = database.get_container_client("EventScoreCard")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    scorecards = list(scorecard_container.query_items(query=query, enable_cross_partition_query=True))
    for entry in scorecards:
        subject="Score Card by "+entry['judgeName']+' for '+entry['category']
        entry['titleHeading']="Score Card For "+entry['category']
        entry['eventTitle']=metaData['eventTitle']
        for iteam in entry['scorecard']:
            entry[iteam]=entry['scorecard'][iteam]
        html_content = read_html_content("ScoreCard.html")
        formatted_html = format_html_content(html_content, entry)
        specific_team_id = entry['teamId']
        emails = []
        for event in emailsData:
            for team in event.get('teamsInfo', []):
                if team['teamName']['id'] == specific_team_id:
                    if team['teamRepresentativeEmail']['email']:
                        emails.append(team['teamRepresentativeEmail']['email'])
                    if team['coachName']['email']:
                        emails.append(team['coachName']['email'])
                    if team['DirectorName']['email']:
                        emails.append(team['DirectorName']['email'])
        createScoreCardPdf(entry['judgeName']+'_ScoreCard.pdf',entry)
        emails = list(filter(None, set(emails)))
        recipient = ', '.join(emails)
        recipient=recipient.split(",")
        for entry in recipient:
            try:
                # Create the email message
                msg = MIMEMultipart()
                msg['From'] = GMAIL_USER
                msg['To'] = entry
                msg['Subject'] = subject
                layout = read_html_content("scorecardLayout.html")
                emailContent={'mailContent':formatted_html}
                html_content = format_html_content(layout, emailContent)
                msg.attach(MIMEText(html_content, 'html'))

                with open(pdf_filename, 'rb') as pdf_file:
                    pdf_attachment = MIMEApplication(pdf_file.read(), _subtype='pdf')
                    pdf_attachment.add_header('Content-Disposition', 'attachment', filename=pdf_filename)
                    msg.attach(pdf_attachment)
                # Connect to Gmail's SMTP server
                with smtplib.SMTP('smtp.gmail.com', 587) as server:
                    server.starttls()  # Upgrade the connection to secure
                    server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                    server.sendmail(GMAIL_USER, recipient, msg.as_string())
            except Exception as e:
                return jsonify({'error': str(e)})
    return jsonify({'message': "success"})
def configureEventOrder(data):
    competition_id = data['EventId']
    scorecard_container = database.get_container_client("EventScoreCard")
    # Query scorecards for the given competition_id
    query = f"SELECT c.category, c.teamId, c.teamName FROM c WHERE c.EventId = @EventId"
    query_params = [{"name": "@EventId", "value": competition_id}]
    listPerformances = list(scorecard_container.query_items(
        query=query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))

    eventOrder_document = {
        "id": generate_unique_id(),
        "EventId": competition_id,
        "categoryOrder": []
    }

    seen = set()
    unique_listPerformances = []
    for performance in listPerformances:
        identifier = (performance['category'], performance['teamId'], performance['teamName'])
        if identifier not in seen:
            seen.add(identifier)
            unique_listPerformances.append(performance)

    # Organize performances by category
    categories = {}
    for performance in unique_listPerformances:
        category = performance.get("category")
        team_id = performance.get("teamId")
        team_name = performance.get("teamName")

        if category not in categories:
            categories[category] = []

        categories[category].append({
            "teamId": team_id,
            "teamName": team_name,
        })

    for category_index, (category, teams) in enumerate(categories.items(), start=1):
        eventOrder_document["categoryOrder"].append({
            "category": category,
            "order": category_index,
            "performances": []
        })

        for team_index, team in enumerate(teams, start=1):
            team_with_order = team.copy()
            team_with_order["order"] = team_index
            eventOrder_document["categoryOrder"][-1]["performances"].append(team_with_order)

    # Container for EventOrderConfig
    Ordercontainer = database.get_container_client("EventOrderConfig")
    
    try:
        # Check if the event order document already exists
        existing_documents = list(Ordercontainer.query_items(
            query="SELECT * FROM c WHERE c.EventId = @EventId",
            parameters=query_params,
            enable_cross_partition_query=True
        ))

        if existing_documents:
            # If exists, replace the document
            existing_document = existing_documents[0]
            updated_document = Ordercontainer.replace_item(item=existing_document['id'], body=eventOrder_document)
            return jsonify(updated_document), 200
        else:
            # If does not exist, create a new document
            eventOrder_document["CreationDateTimeStamp"]=datetime.now().isoformat()
            new_document = Ordercontainer.create_item(body=eventOrder_document)
            return jsonify(new_document), 201

    except exceptions.CosmosResourceNotFoundError:
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
def configureEventOrderMain(data):
    competition_id = data['EventId']
    container = database.get_container_client("EventTeamsJudges")
    meta_conatiner = database.get_container_client("EventMeta")
    # Query scorecards for the given competition_id
    query = f"SELECT c.teamsInfo FROM c WHERE c.EventId = @EventId"
    category_query=f"SELECT c.eventCategory FROM c WHERE c.EventId = @EventId"
    query_params = [{"name": "@EventId", "value": competition_id}]
    listCategory = list(meta_conatiner.query_items(
        query=category_query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))
    listPerformances = list(container.query_items(
        query=query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))

    eventOrder_document = {
        "id": generate_unique_id(),
        "EventId": competition_id,
        "categoryOrder": []
    }

    seen = set()
    unique_listPerformances = []
    for category in listCategory[0]['eventCategory']:
        for performance in listPerformances[0]['teamsInfo']:
            identifier = (category, performance['teamName']['id'], performance['teamName']['name'])
            data = {
            'category': category,
            'teamId': performance['teamName']['id'],
            'teamName': performance['teamName']['name']
            }
            if identifier not in seen:
                seen.add(identifier)
                unique_listPerformances.append(data)

    # Organize performances by category
    categories = {}
    for performance in unique_listPerformances:
        category = performance.get("category")
        team_id = performance.get("teamId")
        team_name = performance.get("teamName")

        if category not in categories:
            categories[category] = []

        categories[category].append({
            "teamId": team_id,
            "teamName": team_name,
        })

    for category_index, (category, teams) in enumerate(categories.items(), start=1):
        eventOrder_document["categoryOrder"].append({
            "category": category,
            "order": category_index,
            "performances": []
        })

        for team_index, team in enumerate(teams, start=1):
            team_with_order = team.copy()
            team_with_order["order"] = team_index
            eventOrder_document["categoryOrder"][-1]["performances"].append(team_with_order)

    # Container for EventOrderConfig
    Ordercontainer = database.get_container_client("EventOrderConfig")
    
    try:
        # Check if the event order document already exists
        existing_documents = list(Ordercontainer.query_items(
            query="SELECT * FROM c WHERE c.EventId = @EventId",
            parameters=query_params,
            enable_cross_partition_query=True
        ))

        if existing_documents:
            # If exists, replace the document
            existing_document = existing_documents[0]
            updated_document = Ordercontainer.replace_item(item=existing_document['id'], body=eventOrder_document)
            return jsonify(updated_document), 200
        else:
            # If does not exist, create a new document
            eventOrder_document["CreationDateTimeStamp"]=datetime.now().isoformat()
            new_document = Ordercontainer.create_item(body=eventOrder_document)
            return jsonify(new_document), 201

    except exceptions.CosmosResourceNotFoundError:
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500        
@app.route('/getEventOrder', methods=['POST'])
def getEventOrder():
    Ordercontainer = database.get_container_client("EventOrderConfig")
    data=request.json
    competition_id=data['EventId']
    try:
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
        eventOrder_document = list(Ordercontainer.query_items(query=query, enable_cross_partition_query=True))
        return  eventOrder_document[0], 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route('/updateEventOrder', methods=['POST'])
def updateEventOrder():
    Ordercontainer = database.get_container_client("EventOrderConfig")
    data=request.json
    competition_id=data['EventId']
    order_id=data['id']
    try:
        updated_document = Ordercontainer.replace_item(item=order_id, body=data)
        return  updated_document, 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
def createScoreCardPdf(filename,data):
    try:
        doc = SimpleDocTemplate(filename, pagesize=letter)
        styles = getSampleStyleSheet()
        elements = []

        # Title
        title_style = styles['Title']
        title_style.fontName = 'Helvetica-Bold'
        title_style.fontSize = 24
        title_style.alignment = TA_CENTER
        title = Paragraph("Score Card", title_style)
        elements.append(title)
        elements.append(Spacer(1, 0.5 * inch))

        for entry in data:
            # Event Title
            event_title_style = styles['Heading1']
            event_title_style.fontName = 'Helvetica-Bold'
            event_title_style.fontSize = 20
            event_title_style.alignment = TA_CENTER
            event_title = Paragraph(f"{entry['eventTitle']}", event_title_style)
            elements.append(event_title)
            elements.append(Spacer(1, 0.25 * inch))

            # Judge and Team Details
            details_style = styles['Normal']
            details_style.fontName = 'Helvetica'
            details_style.fontSize = 12
            details_style.alignment = TA_LEFT
            judge_name = Paragraph(f"<b>Judge:</b> {entry['judgeName']}", details_style)
            team_name = Paragraph(f"<b>Team:</b> {entry['teamName']}", details_style)
            comments = Paragraph(f"<b>Comments:</b> {entry['Comments']}", details_style)
            elements.append(judge_name)
            elements.append(team_name)
            elements.append(comments)
            elements.append(Spacer(1, 0.5 * inch))

            # Performance Table
            table_data = [
                ["Category", "Score"],
                ["Creativity", entry['creativity']],
                ["Difficulty", entry['difficulty']],
                ["Formation", entry['formation']],
                ["Sync", entry['sync']],
                ["Technique", entry['technique']],
                ["Total", entry['total']]
            ]

            table = Table(table_data, colWidths=[2.5 * inch, 1.5 * inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4CAF50')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 0.5 * inch))

        # Build PDF
        doc.build(elements)
    except Exception as e:
         print(jsonify({"error": str(e)}), 500)


def create_pdf(filename, data,eventOrder):
    doc = SimpleDocTemplate(filename, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    title = Paragraph("Event Schedule", styles['Title'])
    elements.append(title)
    elements.append(Paragraph("<br/>", styles['Normal']))

    # Event Title
    event_id = Paragraph(f"{data.get('eventTitle', '')}", styles['Normal'])
    elements.append(event_id)
    elements.append(Paragraph("<br/>", styles['Normal']))
    # Event Venue String
    event_id = Paragraph(f"Venue :{data.get('eventVenue', '')}", styles['Normal'])
    elements.append(event_id)
    elements.append(Paragraph("<br/>", styles['Normal']))
    # Event Data String
    event_id = Paragraph(f"Date and Time :{data.get('eventDateString', '')}", styles['Normal'])
    elements.append(event_id)
    elements.append(Paragraph("<br/>", styles['Normal']))

    # Categories and Performances
    for category in eventOrder['categoryOrder']:
        category_title = Paragraph(f"<b>Category: {category['category']} (Order: {category['order']})</b>", styles['Heading2'])
        elements.append(category_title)
        # Table Data
        table_data = [["Order", "Team Name"]]  # Removed "Team ID"
        for performance in category['performances']:
            table_data.append([performance['order'], performance['teamName']])  # Removed "Team ID"
        # Create Table
        table = Table(table_data, colWidths=[1 * inch, 2.5 * inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 1, black),
        ]))
        elements.append(table)
        elements.append(Paragraph("<br/>", styles['Normal']))

    # Build PDF
    doc.build(elements)

# Route to send email with PDF attachment
@app.route('/sendEventSchedule', methods=['POST'])
def send_email_with_pdf():
    data = request.json
    competition_id = data.get('EventId')
    # Initialize Cosmos Client
    container = database.get_container_client("EventMeta")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    items = container.query_items(query=query, enable_cross_partition_query=True)
    eventCategorys = list(items)
    data=eventCategorys[0]
    query=f"SELECT *  FROM c WHERE c.EventId = '{competition_id}' "
    subject = (data.get('eventTitle', '') + '|' +
           data.get('eventDateString', '') + '|' +
           data.get('eventVenue', '') + ' Schedule')    # Create the PDF
    Ordercontainer = database.get_container_client("EventOrderConfig")
    competition_id=data['EventId']
    container = database.get_container_client("EventTeamsJudges")
    emailsData = list(container.query_items(query=query, enable_cross_partition_query=True))
    # Extract emails
    emails = []

# Extract team representative, coach, and director emails
    for event in emailsData:
        for team in event.get('teamsInfo', []):
            if team['teamRepresentativeEmail']['email']:
                emails.append(team['teamRepresentativeEmail']['email'])
            if team['coachName']['email']:
                emails.append(team['coachName']['email'])
            if team['DirectorName']['email']:
                emails.append(team['DirectorName']['email'])
    # Remove empty strings (if any) and duplicates
    emails = list(filter(None, set(emails)))
    recipient = ','.join(emails)
    recipient=recipient.split(",")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    eventOrder_document = list(Ordercontainer.query_items(query=query, enable_cross_partition_query=True))
    #create_pdf(pdf_filename, data,eventOrder_document[0])
    # Read and format HTML content
    firsthtml = read_html_content("EventSchedule-converted.html")
    firsthtml=format_html_content(firsthtml, data)
    for category in eventOrder_document[0]['categoryOrder']:
        html_content = read_html_content("categoryEventTag.html")
        tagData={}
        tagData['Category']=category['category']
        # Table Data
        table_data = [["Order", "Team Name"]]  # Removed "Team ID"
        orderTags=''
        for performance in category['performances']:
            perData={}
            entryTag = read_html_content("orderandTeamTag.html")
            perData['order']=performance['order']
            perData['TeamName']=performance['teamName']
            orderTags=orderTags+format_html_content(entryTag, perData)
        tagData['orderTags']  = orderTags
        firsthtml = firsthtml+format_html_content(html_content, tagData)
    firsthtml=firsthtml+read_html_content("EventScheduleEnd.html")
    for entry in recipient:
        try:
            # Create the email message
            msg = MIMEMultipart()
            msg['From'] = GMAIL_USER
            msg['To'] = entry
            msg['Subject'] = subject
            layout = read_html_content("scorecardLayout.html")
            emailContent={'mailContent':firsthtml}
            html_content = format_html_content(layout, emailContent)
            msg.attach(MIMEText(html_content, 'html'))


            # Connect to Gmail's SMTP server
            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.starttls()  # Upgrade the connection to secure
                server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                server.sendmail(GMAIL_USER, recipient, msg.as_string())
            # Clean up
        except Exception as e:
            print( jsonify({'error': str(e)}))
    return jsonify({'message': 'Email sent successfully with PDF attachment'})
        
if __name__ == "__main__":
    app.run(host="0.0.0.0",port=5001)



@app.route('/getBanners', methods=['GET'])
def get_banner():
    try:
        # Get the container client inside the function
        container = database.get_container_client("BannerImgUrls")
        
        # Query to get all items from the container
        banners = list(container.read_all_items())
        
        # Return the data as JSON
        return jsonify(banners), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500      
@app.route('/removeBanner', methods=['POST'])
def remove_banner():
    try:
        # Get the container client
        container = database.get_container_client("BannerImgUrls")
        
        # Get the BannerId from the POST request body
        data = request.get_json()
        banner_id = data.get("BannerId")
        
        if not banner_id:
            return jsonify({"error": "BannerId is required"}), 400

        # Query to find the item based on the BannerId
        query = f"SELECT * FROM c WHERE c.BannerId = '{banner_id}'"
        items = list(container.query_items(query=query, enable_cross_partition_query=True))
        
        if not items:
            return jsonify({"error": "Banner not found"}), 404

        # Delete the item(s) based on BannerId
        for item in items:
            container.delete_item(item, partition_key=item['id'])

        return jsonify({"message": f"Banner with BannerId {banner_id} deleted successfully"}), 200
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
    
    # Ensure EventId is in the data
    if "EventId" not in data:
        return jsonify({"error": "EventId is required"}), 400
    data["id"] = generate_unique_id()
    data["status"] = "Scheduled"
    data["CreationDateTimeStamp"]= datetime.now().isoformat()
    container = database.get_container_client("EventMeta")
    # Query to check if a competition with the given EventId already exists
    query = "SELECT * FROM c WHERE c.EventId = @EventId"
    query_params = [
        {"name": "@EventId", "value": data["EventId"]}
    ]

    try:
        # Check if the competition already exists
        existing_items = list(container.query_items(
            query=query,
            parameters=query_params,
            enable_cross_partition_query=True
        ))
        if existing_items:
            # If the competition exists, replace it
            existing_item = existing_items[0]
            updated_item = container.replace_item(item=existing_item['id'], body=data)
            return jsonify({"eventId": data["EventId"]}), 200
        else:
            # If the competition does not exist, create a new one
            new_item = container.create_item(body=data)
            return jsonify({"eventId": data["EventId"]}), 201
    except exceptions.CosmosResourceNotFoundError:
        # Handle the case where the container or database does not exist
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        # Handle other Cosmos DB errors
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        # Handle any other exceptions
        return jsonify({"error": str(e)}), 500


@app.route('/updateTeams', methods=['POST'])
def createTeams():
    data = request.json
    # Ensure EventId is in the data
    if "EventId" not in data:
        return jsonify({"error": "EventId is required"}), 400
    # Generate a unique ID for the record (if necessary)
    data["id"] = generate_unique_id()
    data["CreationDateTimeStamp"]= datetime.now().isoformat()
    container = database.get_container_client("EventTeamsJudges")
    try:
        # Check if the record with the given EventId already exists
        query = "SELECT * FROM c WHERE c.EventId=@eventId"
        parameters = [{"name": "@eventId", "value": data["EventId"]}]
        existing_records = list(container.query_items(query=query, parameters=parameters, enable_cross_partition_query=True))
        if existing_records:
            # Record exists, update it
            existing_record = existing_records[0]
            # Update the existing record with new data
            container.replace_item(item=existing_record["id"], body=data)
            configureEventOrderMain(data) 
            return jsonify({"eventId": data["EventId"]}), 200
        else:
            # Record does not exist, create a new one
            container.create_item(body=data)
            configureEventOrderMain(data) 
            return jsonify({"eventId": data["EventId"]}), 201
    except exceptions.CosmosResourceNotFoundError:
        # Handle the case where the container or database does not exist
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        # Handle other Cosmos DB errors
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        # Handle any other exceptions
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
        
        # Define the scorecard access token document
        scorecardAccessTokens = {
            'id': generate_unique_id(),
            'EventId': data["EventId"],
            'judgeId': judge_id,
            'judgeName': judge_name,
            'HostAccess': False,
            'JudgeAccess': True,
            'CoachAccess': False,
            'TokenId': generate_token(),
            'CreationDateTimeStamp':datetime.now().isoformat()
        }

        # Query to check if token already exists for this judge and event
        query = "SELECT * FROM c WHERE c.EventId = @EventId AND c.judgeId = @judgeId"
        query_params = [
            {"name": "@EventId", "value": data["EventId"]},
            {"name": "@judgeId", "value": judge_id}
        ]

        try:
            # Check for existing tokens
            existing_tokens = list(accessTokenContainer.query_items(
                query=query,
                parameters=query_params,
                enable_cross_partition_query=True
            ))

            if existing_tokens:
                # If token exists, replace it
                existing_token = existing_tokens[0]
                scorecardAccessTokens['TokenId']=existing_token['TokenId']
                updated_token = accessTokenContainer.replace_item(item=existing_token['id'], body=scorecardAccessTokens)
                print(f"Updated access token for judge {judge_id}: {updated_token}")
            else:
                # If token does not exist, create a new one
                created_token = accessTokenContainer.create_item(body=scorecardAccessTokens)
                print(f"Created new access token for judge {judge_id}: {created_token}")
                
        except exceptions.CosmosHttpResponseError as e:
            # Log the error and continue; individual token creation or replacement failures should not stop the process
            print(f"Failed to process access token for judge {judge_id}: {e}")
        except Exception as e:
            # Handle unexpected errors
            print(f"Unexpected error for judge {judge_id}: {e}")


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
            'TokenId':generate_token(),
            'CreationDateTimeStamp':datetime.now().isoformat()
        }
        try: # Insert scorecard document into container
            accessTokenContainer.create_item(body=scorecardAccessTokens)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route('/CreateHostAccess', methods=['POST'])
def generateAccessTokensHostAccess():
    data=request.json
    HostConatiner = database.get_container_client("EventHostMeta")
    scorecardAccessTokens = {
        'id':generate_unique_id(),
        'HostId':generate_unique_id(),
        'Email':data['Email'],
        'CreationDateTimeStamp':datetime.now().isoformat()
    }
    accessTokenContainer = database.get_container_client("HostAccessRequests")
    try:
        # Insert scorecard document into container
        HostConatiner.create_item(body=scorecardAccessTokens)
        query = f"SELECT * FROM HostAccessRequests c WHERE c.Email = '{data['Email']}'"
        items = list(accessTokenContainer.query_items(query=query, enable_cross_partition_query=True))

        # If item(s) found, delete them
        for item in items:
            accessTokenContainer.delete_item(item=item['id'], partition_key=item['id'])
        
        return jsonify({"message": "Successfully Created Host Access"}), 200
        return jsonify({"message": "Successfully Created Host Access "}), 200
    except Exception as e:
        print("this is tyhe error"+e)
        return jsonify({"error": str(e)}), 500
import random
import string

def generate_code(length=6):
    characters = string.ascii_letters + string.digits
    code = ''.join(random.choice(characters) for _ in range(length))
    return code

# Example usage
print(generate_code(6))  # Generates a 6-character random code

CLIENT_ID = 'd7b1ed96-6e95-4354-af2a-544869f09e55'
CLIENT_SECRET = 'cfc8Q~2epL9FdAtlvwCEjwCmvrsJ-dDVKSj1Zclo'
TENANT_ID = 'eccdeba0-716d-4614-9824-ff4754cf84a9'
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["https://graph.microsoft.com/.default"]



# MSAL client instance
app_msal = ConfidentialClientApplication(
    CLIENT_ID,
    authority=AUTHORITY,
    client_credential=CLIENT_SECRET
)

GMAIL_USER = 'nandhasriramsabbina@gmail.com'
GMAIL_APP_PASSWORD = 'fngm ypaw glfo tgvo'

@app.route('/SentOtp', methods=['POST'])
def SentOtp():
    data = request.json
    emails = data['Email']
    recipient = emails
    subject = 'Email OTP Verification'
    html_content = read_html_content("emailInvite.html")
    otp = generate_code(6)
    
    # Save OTP to the database
    accessTokenContainer = database.get_container_client("OtpMeta")
    otpDoc = {
        'id': generate_unique_id(),
        'Email': data['Email'],
        'Otp': otp,
        'CreationDateTimeStamp': datetime.now().isoformat()
    }
    accessTokenContainer.create_item(body=otpDoc)
    
    # Format the email content with OTP
    html_content = format_html_content(html_content, otpDoc)
    layout = read_html_content("scorecardLayout.html")
    emailContent = {'mailContent': html_content}
    html_content = format_html_content(layout, emailContent)

    try:
        # Create the email message
        msg = MIMEMultipart()
        msg['From'] = GMAIL_USER
        msg['To'] = recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(html_content, 'html'))
        
        # Connect to Gmail's SMTP server
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()  # Upgrade the connection to secure
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, recipient, msg.as_string())
        
        return jsonify({'message': 'Email sent successfully'})
    except Exception as e:
        return jsonify({'error': str(e)})
    
@app.route('/OtpVerification', methods=['POST'])
def OtpVerification():
    data=request.json
    otpContainer = database.get_container_client("OtpMeta")
    try:
        validationQuery = f"SELECT * FROM c WHERE c.Email = '{data['Email']}' AND c.Otp = '{data['OTP_CODE']}'"
        Tokens = list(otpContainer.query_items(query=validationQuery, enable_cross_partition_query=True))
        if(len(Tokens)>0):
            result={'validation':'true'}
        else:
            result={'validation':'false'}
        return jsonify(result), 200
        # Insert scorecard document into container
    except Exception as e:
        return jsonify({"error": str(e)}), 500   
# Define the function to delete old OTP entries
# def delete_old_otps():
#     ten_minutes_ago = datetime.now() - timedelta(minutes=10)
#     query = "SELECT * FROM c WHERE c.CreationDateTimeStamp < @timestamp"
#     parameters = [{'name': '@timestamp', 'value': ten_minutes_ago.isoformat()}]
#     otpContainer = database.get_container_client("OtpMeta")
#     old_otps = otpContainer.query_items(query=query, parameters=parameters, enable_cross_partition_query=True)
#     for otp in old_otps:
#         otpContainer.delete_item(item=otp, partition_key=otp['id'])

# # Setup APScheduler to run the delete_old_otps function every minute
# scheduler = BackgroundScheduler()
# scheduler.add_job(delete_old_otps, 'interval', minutes=1)
# scheduler.start()     
@app.route('/createLoginDetails', methods=['POST'])
def createAccount():
    data=request.json
    accessTokenContainer = database.get_container_client("EventAuthKeys")
    scorecardAccessTokens = {
        'id':generate_unique_id(),
        'Email':data['Email'],
        'Password':data['Password'],
        'CreationDateTimeStamp':datetime.now().isoformat()
    }
    try:
        # Insert scorecard document into container
        accessTokenContainer.create_item(body=scorecardAccessTokens)
        if(data['HostAccessRequest']=='true'):
            RequestContainer = database.get_container_client("HostAccessRequests")
            RequestContainer.create_item(body=scorecardAccessTokens)
        return jsonify({"message": "Successfully Created Account "}), 200
    except Exception as e:
        print("this is tyhe error"+e)
        return jsonify({"error": str(e)}), 500

@app.route('/approveHostAccess', methods=['POST'])
def approveHostAccess():
    data=request.json
    result={}
    accessTokenContainer = database.get_container_client("HostAccessRequests")
    try:
        container = database.get_container_client("EventMeta")
        query = "SELECT * FROM c"
        items = accessTokenContainer.query_items(query=query, enable_cross_partition_query=True)
        result = list(items)
        return jsonify(result), 200
        # Insert scorecard document into container
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/authLoginDetails', methods=['POST'])
def authLoginDetails():
    data=request.json
    result={}
    accessTokenContainer = database.get_container_client("EventAuthKeys")
    try:
        validationQuery = f"SELECT * FROM c WHERE c.Email = '{data['Email']}' AND c.Password = '{data['Password']}'"
        Tokens = list(accessTokenContainer.query_items(query=validationQuery, enable_cross_partition_query=True))
        if(len(Tokens)>0):
            accessTokenContainer = database.get_container_client("EventHostMeta")
            validationQuery = f"SELECT * FROM c WHERE c.Email = '{data['Email']}'"
            access=list(accessTokenContainer.query_items(query=validationQuery, enable_cross_partition_query=True))
            if(len(access)>0):
                result={'validation':'true','HostAccess':'true','HostId':access[0]['HostId'],'OwnerAccess':'true' if data['Email'] == 'nandhashriramsabbina@outlook.com' else 'false'}
            else:
                result={'validation':'true','HostAccess':'false','OwnerAccess':'true' if data['Email'] == 'nandhashriramsabbina@outlook.com' else 'false'}    
        else:
            result={'validation':'false','HostAccess':'false','OwnerAccess':'true' if data['Email'] == 'nandhashriramsabbina@outlook.com' else 'false'}
        return jsonify(result), 200
        # Insert scorecard document into container
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
    
#saveScoreParameters   

@app.route('/saveScoreParameters', methods=['POST'])
def update_Scorecard():
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
    
@app.route('/getBanners', methods=['GET'])
def getBanners():
    try:
        container = database.get_container_client("BannerImgUrls")
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
    
def get_category_entry(scorecardMeta, category_name):
    return next((entry for entry in scorecardMeta if entry['category'] == category_name), None)

def add_scorecard(data):
    competition_id = data.get('EventId')

    # Initialize Cosmos Client
    container = database.get_container_client("EventMeta")
    query = f"SELECT c.eventCategory, c.scorecardMeta FROM c WHERE c.EventId = '{competition_id}'"

    try:
        # Fetch event category and scorecard meta
        items = container.query_items(query=query, enable_cross_partition_query=True)
        eventCategorys = list(items)
        if not eventCategorys:
            return jsonify({"error": "No event category found for the given EventId"}), 404

        eventCategorys = eventCategorys[0]
        eventScoreCardMeta = eventCategorys.get('scorecardMeta', [])
        eventCategorys = eventCategorys.get('eventCategory', [])

        # Initialize the scorecard container client
        scorecard_container = database.get_container_client("EventScoreCard")

        # Create scorecard entry for every judge * team combination
        for category in eventCategorys:
            for judge in data.get('JudegsInfo', []):
                judge_id = judge.get('id')
                judge_name = judge.get('name')
                for team in data.get('teamsInfo', []):
                    team_id = team.get('teamName', {}).get('id')
                    team_name = team.get('teamName', {}).get('name')

                    # Check for existing scorecard
                    unique_query = f"SELECT c.id FROM c WHERE c.EventId = '{data['EventId']}' AND c.judgeId = '{judge_id}' AND c.teamId = '{team_id}' AND c.category = '{category}'"
                    existing_entries = list(scorecard_container.query_items(query=unique_query, enable_cross_partition_query=True))

                    if existing_entries:
                        # Skip creating the entry if it already exists
                        continue

                    # Initialize scorecard with dynamic fields based on scorecardMeta
                    scorecard = {param['name']: 0 for param in get_category_entry(eventScoreCardMeta, category).get('parameters', [])}
                    scorecard['total'] = 0  # Initialize total score

                    # Create initial scorecard document
                    scorecard_document = {
                        'id': generate_unique_id(),
                        'EventId': data["EventId"],
                        'judgeId': judge_id,
                        'judgeName': judge_name,
                        'teamId': team_id,
                        'teamName': team_name,
                        'category': category,
                        'teamMemberId': None,  # Assuming we don't have specific team member ID here
                        'scorecard': scorecard,
                        'comments': '',
                        'CreationDateTimeStamp': datetime.now().isoformat()
                    }

                    # Insert scorecard document into container
                    try:
                        scorecard_container.create_item(body=scorecard_document)
                    except Exception as e:
                        return jsonify({"error": str(e)}), 500

        return jsonify({"status": "Scorecards created successfully"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/update_scores', methods=['POST'])
def update_scores():
    try:
        data = request.json
        scorecard_id=data["id"]
        eventId=data["EventId"]
        new_scores=data["scorecard"]
        comments=data["comment"]
        scorecard_container = database.get_container_client("EventScoreCard")
        # Retrieve the scorecard document from the database
        scorecard_document = scorecard_container.read_item(item=scorecard_id,partition_key=eventId)
        # Update the scores in the scorecard document
        scorecard_document['scorecard'].update(new_scores)
        scorecard_document['comments']=comments
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
        category=data.get('category')
        if not competition_id or not judge_id:
            return jsonify({"error": "Please provide both competitionId and judgeId in the request body"}), 400
        scorecard_container = database.get_container_client("EventScoreCard")
            # Query scorecards for the given competition_id and judge_id
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}' AND c.judgeId = '{judge_id}' AND c.teamId='{teamId}' AND c.category='{category}'"
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
        competition_id = data.get('EventId')

        # Initialize Cosmos DB container
        scorecard_container = database.get_container_client("EventScoreCard")
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
        scorecards = list(scorecard_container.query_items(query=query, enable_cross_partition_query=True))

        # Initialize dictionary to store scores per category
        category_scores = {}

        # Process each scorecard entry
        for scorecard in scorecards:
            team_id = scorecard.get('teamId')
            team_name = scorecard.get('teamName')
            category = scorecard.get('category')
            scorecard_data = scorecard.get('scorecard', {})

            # Compute score dynamically, excluding 'total'
            score_fields = [key for key in scorecard_data if key != 'total']
            score = sum(scorecard_data.get(field, 0) for field in score_fields)

            # Create a unique key for each team per category
            team_category_key = (team_name, category)

            if category not in category_scores:
                category_scores[category] = {}

            if team_category_key not in category_scores[category]:
                category_scores[category][team_category_key] = {
                    'teamId': team_id,
                    'teamName': team_name,
                    'category': category,
                    'total_score': 0
                }

            category_scores[category][team_category_key]['total_score'] += score

        # Prepare leaderboard sorted by categories and scores
        leaderboard = {}
        for category, scores in category_scores.items():
            sorted_scores = sorted(scores.values(), key=lambda x: x['total_score'], reverse=True)
            leaderboard[category] = sorted_scores

        return jsonify({"leaderboard": leaderboard}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


OUTLOOK_USER='nandhashriramsabbina@outlook.com'
OUTLOOK_PASSWORD='eakwnysdkybugfuh'  # Use App Password if 2-Step Verification is enabled
def read_html_content(file_path):
    with open(file_path, 'r') as file:
        return file.read()

@app.route('/send-email', methods=['POST'])
def send_email():
    data=request.json
    emails = data['emails']
    recipient = ', '.join(emails)
    recipient=recipient.split(",")
    subject = 'Test'
    html_content = read_html_content("emailInvite.html")
    formatted_html = format_html_content(html_content, entry)
    html_content.replace("PLACEHOLDER_COMPANY_NAME","Productions")
    html_content.replace("PLACEHOLDER_EVENT_TITLE","Productions")
    try:
        # Create the email message
        msg = MIMEMultipart()
        msg['From'] = GMAIL_USER
        msg['To'] = recipient
        msg['Subject'] = subject
        layout = read_html_content("scorecardLayout.html")
        emailContent={'mailContent':html_content}
        html_content = format_html_content(layout, emailContent)
        msg.attach(MIMEText(html_content, 'html'))
        # Connect to Gmail's SMTP server
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()  # Upgrade the connection to secure
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, recipient, msg.as_string())
    except Exception as e:
            print( jsonify({'error': str(e)}))
    return jsonify({'message': 'Email sent successfully with PDF attachment'})
def format_html_content(template, data):
    for key, value in data.items():
        placeholder = '{{' + key + '}}'
        template = template.replace(placeholder, str(value))
    return template



@app.route('/send-scorecard', methods=['POST'])
def sendScoreCardsemail():
    data=request.json
    pdf_filename="ScoreCard.pdf"
    competition_id=data['EventId']
    container = database.get_container_client("EventMeta")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    items = container.query_items(query=query, enable_cross_partition_query=True)
    metaData = list(items)
    metaData=metaData[0]
    container = database.get_container_client("EventTeamsJudges")
    query=f"SELECT *  FROM c WHERE c.EventId = '{competition_id}' "
    emailsData = list(container.query_items(query=query, enable_cross_partition_query=True))
    # Extract emails
    emails = []
    scorecard_container = database.get_container_client("EventScoreCard")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    scorecards = list(scorecard_container.query_items(query=query, enable_cross_partition_query=True))
    for entry in scorecards:
        subject="Score Card by "+entry['judgeName']+' for '+entry['category']
        entry['titleHeading']="Score Card For "+entry['category']
        entry['eventTitle']=metaData['eventTitle']
        for iteam in entry['scorecard']:
            entry[iteam]=entry['scorecard'][iteam]
        html_content = read_html_content("ScoreCard.html")
        formatted_html = format_html_content(html_content, entry)
        specific_team_id = entry['teamId']
        emails = []
        for event in emailsData:
            for team in event.get('teamsInfo', []):
                if team['teamName']['id'] == specific_team_id:
                    if team['teamRepresentativeEmail']['email']:
                        emails.append(team['teamRepresentativeEmail']['email'])
                    if team['coachName']['email']:
                        emails.append(team['coachName']['email'])
                    if team['DirectorName']['email']:
                        emails.append(team['DirectorName']['email'])
        createScoreCardPdf(entry['judgeName']+'_ScoreCard.pdf',entry)
        emails = list(filter(None, set(emails)))
        recipient = ', '.join(emails)
        recipient=recipient.split(",")
        for entry in recipient:
            try:
                # Create the email message
                msg = MIMEMultipart()
                msg['From'] = GMAIL_USER
                msg['To'] = entry
                msg['Subject'] = subject
                layout = read_html_content("scorecardLayout.html")
                emailContent={'mailContent':formatted_html}
                html_content = format_html_content(layout, emailContent)
                msg.attach(MIMEText(html_content, 'html'))

                with open(pdf_filename, 'rb') as pdf_file:
                    pdf_attachment = MIMEApplication(pdf_file.read(), _subtype='pdf')
                    pdf_attachment.add_header('Content-Disposition', 'attachment', filename=pdf_filename)
                    msg.attach(pdf_attachment)
                # Connect to Gmail's SMTP server
                with smtplib.SMTP('smtp.gmail.com', 587) as server:
                    server.starttls()  # Upgrade the connection to secure
                    server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                    server.sendmail(GMAIL_USER, recipient, msg.as_string())
            except Exception as e:
                return jsonify({'error': str(e)})
    return jsonify({'message': "success"})
def configureEventOrder(data):
    competition_id = data['EventId']
    scorecard_container = database.get_container_client("EventScoreCard")
    # Query scorecards for the given competition_id
    query = f"SELECT c.category, c.teamId, c.teamName FROM c WHERE c.EventId = @EventId"
    query_params = [{"name": "@EventId", "value": competition_id}]
    listPerformances = list(scorecard_container.query_items(
        query=query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))

    eventOrder_document = {
        "id": generate_unique_id(),
        "EventId": competition_id,
        "categoryOrder": []
    }

    seen = set()
    unique_listPerformances = []
    for performance in listPerformances:
        identifier = (performance['category'], performance['teamId'], performance['teamName'])
        if identifier not in seen:
            seen.add(identifier)
            unique_listPerformances.append(performance)

    # Organize performances by category
    categories = {}
    for performance in unique_listPerformances:
        category = performance.get("category")
        team_id = performance.get("teamId")
        team_name = performance.get("teamName")

        if category not in categories:
            categories[category] = []

        categories[category].append({
            "teamId": team_id,
            "teamName": team_name,
        })

    for category_index, (category, teams) in enumerate(categories.items(), start=1):
        eventOrder_document["categoryOrder"].append({
            "category": category,
            "order": category_index,
            "performances": []
        })

        for team_index, team in enumerate(teams, start=1):
            team_with_order = team.copy()
            team_with_order["order"] = team_index
            eventOrder_document["categoryOrder"][-1]["performances"].append(team_with_order)

    # Container for EventOrderConfig
    Ordercontainer = database.get_container_client("EventOrderConfig")
    
    try:
        # Check if the event order document already exists
        existing_documents = list(Ordercontainer.query_items(
            query="SELECT * FROM c WHERE c.EventId = @EventId",
            parameters=query_params,
            enable_cross_partition_query=True
        ))

        if existing_documents:
            # If exists, replace the document
            existing_document = existing_documents[0]
            updated_document = Ordercontainer.replace_item(item=existing_document['id'], body=eventOrder_document)
            return jsonify(updated_document), 200
        else:
            # If does not exist, create a new document
            eventOrder_document["CreationDateTimeStamp"]=datetime.now().isoformat()
            new_document = Ordercontainer.create_item(body=eventOrder_document)
            return jsonify(new_document), 201

    except exceptions.CosmosResourceNotFoundError:
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
def configureEventOrderMain(data):
    competition_id = data['EventId']
    container = database.get_container_client("EventTeamsJudges")
    meta_conatiner = database.get_container_client("EventMeta")
    # Query scorecards for the given competition_id
    query = f"SELECT c.teamsInfo FROM c WHERE c.EventId = @EventId"
    category_query=f"SELECT c.eventCategory FROM c WHERE c.EventId = @EventId"
    query_params = [{"name": "@EventId", "value": competition_id}]
    listCategory = list(meta_conatiner.query_items(
        query=category_query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))
    listPerformances = list(container.query_items(
        query=query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))

    eventOrder_document = {
        "id": generate_unique_id(),
        "EventId": competition_id,
        "categoryOrder": []
    }

    seen = set()
    unique_listPerformances = []
    for category in listCategory[0]['eventCategory']:
        for performance in listPerformances[0]['teamsInfo']:
            identifier = (category, performance['teamName']['id'], performance['teamName']['name'])
            data = {
            'category': category,
            'teamId': performance['teamName']['id'],
            'teamName': performance['teamName']['name']
            }
            if identifier not in seen:
                seen.add(identifier)
                unique_listPerformances.append(data)

    # Organize performances by category
    categories = {}
    for performance in unique_listPerformances:
        category = performance.get("category")
        team_id = performance.get("teamId")
        team_name = performance.get("teamName")

        if category not in categories:
            categories[category] = []

        categories[category].append({
            "teamId": team_id,
            "teamName": team_name,
        })

    for category_index, (category, teams) in enumerate(categories.items(), start=1):
        eventOrder_document["categoryOrder"].append({
            "category": category,
            "order": category_index,
            "performances": []
        })

        for team_index, team in enumerate(teams, start=1):
            team_with_order = team.copy()
            team_with_order["order"] = team_index
            eventOrder_document["categoryOrder"][-1]["performances"].append(team_with_order)

    # Container for EventOrderConfig
    Ordercontainer = database.get_container_client("EventOrderConfig")
    
    try:
        # Check if the event order document already exists
        existing_documents = list(Ordercontainer.query_items(
            query="SELECT * FROM c WHERE c.EventId = @EventId",
            parameters=query_params,
            enable_cross_partition_query=True
        ))

        if existing_documents:
            # If exists, replace the document
            existing_document = existing_documents[0]
            updated_document = Ordercontainer.replace_item(item=existing_document['id'], body=eventOrder_document)
            return jsonify(updated_document), 200
        else:
            # If does not exist, create a new document
            eventOrder_document["CreationDateTimeStamp"]=datetime.now().isoformat()
            new_document = Ordercontainer.create_item(body=eventOrder_document)
            return jsonify(new_document), 201

    except exceptions.CosmosResourceNotFoundError:
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500        
@app.route('/getEventOrder', methods=['POST'])
def getEventOrder():
    Ordercontainer = database.get_container_client("EventOrderConfig")
    data=request.json
    competition_id=data['EventId']
    try:
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
        eventOrder_document = list(Ordercontainer.query_items(query=query, enable_cross_partition_query=True))
        return  eventOrder_document[0], 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route('/updateEventOrder', methods=['POST'])
def updateEventOrder():
    Ordercontainer = database.get_container_client("EventOrderConfig")
    data=request.json
    competition_id=data['EventId']
    order_id=data['id']
    try:
        updated_document = Ordercontainer.replace_item(item=order_id, body=data)
        return  updated_document, 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
def createScoreCardPdf(filename,data):
    try:
        doc = SimpleDocTemplate(filename, pagesize=letter)
        styles = getSampleStyleSheet()
        elements = []

        # Title
        title_style = styles['Title']
        title_style.fontName = 'Helvetica-Bold'
        title_style.fontSize = 24
        title_style.alignment = TA_CENTER
        title = Paragraph("Score Card", title_style)
        elements.append(title)
        elements.append(Spacer(1, 0.5 * inch))

        for entry in data:
            # Event Title
            event_title_style = styles['Heading1']
            event_title_style.fontName = 'Helvetica-Bold'
            event_title_style.fontSize = 20
            event_title_style.alignment = TA_CENTER
            event_title = Paragraph(f"{entry['eventTitle']}", event_title_style)
            elements.append(event_title)
            elements.append(Spacer(1, 0.25 * inch))

            # Judge and Team Details
            details_style = styles['Normal']
            details_style.fontName = 'Helvetica'
            details_style.fontSize = 12
            details_style.alignment = TA_LEFT
            judge_name = Paragraph(f"<b>Judge:</b> {entry['judgeName']}", details_style)
            team_name = Paragraph(f"<b>Team:</b> {entry['teamName']}", details_style)
            comments = Paragraph(f"<b>Comments:</b> {entry['Comments']}", details_style)
            elements.append(judge_name)
            elements.append(team_name)
            elements.append(comments)
            elements.append(Spacer(1, 0.5 * inch))

            # Performance Table
            table_data = [
                ["Category", "Score"],
                ["Creativity", entry['creativity']],
                ["Difficulty", entry['difficulty']],
                ["Formation", entry['formation']],
                ["Sync", entry['sync']],
                ["Technique", entry['technique']],
                ["Total", entry['total']]
            ]

            table = Table(table_data, colWidths=[2.5 * inch, 1.5 * inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4CAF50')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 0.5 * inch))

        # Build PDF
        doc.build(elements)
    except Exception as e:
         print(jsonify({"error": str(e)}), 500)


def create_pdf(filename, data,eventOrder):
    doc = SimpleDocTemplate(filename, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    title = Paragraph("Event Schedule", styles['Title'])
    elements.append(title)
    elements.append(Paragraph("<br/>", styles['Normal']))

    # Event Title
    event_id = Paragraph(f"{data.get('eventTitle', '')}", styles['Normal'])
    elements.append(event_id)
    elements.append(Paragraph("<br/>", styles['Normal']))
    # Event Venue String
    event_id = Paragraph(f"Venue :{data.get('eventVenue', '')}", styles['Normal'])
    elements.append(event_id)
    elements.append(Paragraph("<br/>", styles['Normal']))
    # Event Data String
    event_id = Paragraph(f"Date and Time :{data.get('eventDateString', '')}", styles['Normal'])
    elements.append(event_id)
    elements.append(Paragraph("<br/>", styles['Normal']))

    # Categories and Performances
    for category in eventOrder['categoryOrder']:
        category_title = Paragraph(f"<b>Category: {category['category']} (Order: {category['order']})</b>", styles['Heading2'])
        elements.append(category_title)
        # Table Data
        table_data = [["Order", "Team Name"]]  # Removed "Team ID"
        for performance in category['performances']:
            table_data.append([performance['order'], performance['teamName']])  # Removed "Team ID"
        # Create Table
        table = Table(table_data, colWidths=[1 * inch, 2.5 * inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 1, black),
        ]))
        elements.append(table)
        elements.append(Paragraph("<br/>", styles['Normal']))

    # Build PDF
    doc.build(elements)

# Route to send email with PDF attachment
@app.route('/sendEventSchedule', methods=['POST'])
def send_email_with_pdf():
    data = request.json
    competition_id = data.get('EventId')
    # Initialize Cosmos Client
    container = database.get_container_client("EventMeta")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    items = container.query_items(query=query, enable_cross_partition_query=True)
    eventCategorys = list(items)
    data=eventCategorys[0]
    query=f"SELECT *  FROM c WHERE c.EventId = '{competition_id}' "
    subject = (data.get('eventTitle', '') + '|' +
           data.get('eventDateString', '') + '|' +
           data.get('eventVenue', '') + ' Schedule')    # Create the PDF
    Ordercontainer = database.get_container_client("EventOrderConfig")
    competition_id=data['EventId']
    container = database.get_container_client("EventTeamsJudges")
    emailsData = list(container.query_items(query=query, enable_cross_partition_query=True))
    # Extract emails
    emails = []

# Extract team representative, coach, and director emails
    for event in emailsData:
        for team in event.get('teamsInfo', []):
            if team['teamRepresentativeEmail']['email']:
                emails.append(team['teamRepresentativeEmail']['email'])
            if team['coachName']['email']:
                emails.append(team['coachName']['email'])
            if team['DirectorName']['email']:
                emails.append(team['DirectorName']['email'])
    # Remove empty strings (if any) and duplicates
    emails = list(filter(None, set(emails)))
    recipient = ','.join(emails)
    recipient=recipient.split(",")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    eventOrder_document = list(Ordercontainer.query_items(query=query, enable_cross_partition_query=True))
    #create_pdf(pdf_filename, data,eventOrder_document[0])
    # Read and format HTML content
    firsthtml = read_html_content("EventSchedule-converted.html")
    firsthtml=format_html_content(firsthtml, data)
    for category in eventOrder_document[0]['categoryOrder']:
        html_content = read_html_content("categoryEventTag.html")
        tagData={}
        tagData['Category']=category['category']
        # Table Data
        table_data = [["Order", "Team Name"]]  # Removed "Team ID"
        orderTags=''
        for performance in category['performances']:
            perData={}
            entryTag = read_html_content("orderandTeamTag.html")
            perData['order']=performance['order']
            perData['TeamName']=performance['teamName']
            orderTags=orderTags+format_html_content(entryTag, perData)
        tagData['orderTags']  = orderTags
        firsthtml = firsthtml+format_html_content(html_content, tagData)
    firsthtml=firsthtml+read_html_content("EventScheduleEnd.html")
    for entry in recipient:
        try:
            # Create the email message
            msg = MIMEMultipart()
            msg['From'] = GMAIL_USER
            msg['To'] = entry
            msg['Subject'] = subject
            layout = read_html_content("scorecardLayout.html")
            emailContent={'mailContent':firsthtml}
            html_content = format_html_content(layout, emailContent)
            msg.attach(MIMEText(html_content, 'html'))


            # Connect to Gmail's SMTP server
            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.starttls()  # Upgrade the connection to secure
                server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                server.sendmail(GMAIL_USER, recipient, msg.as_string())
            # Clean up
        except Exception as e:
            print( jsonify({'error': str(e)}))
    return jsonify({'message': 'Email sent successfully with PDF attachment'})
        
if __name__ == "__main__":
    app.run(host="0.0.0.0",port=5001)



@app.route('/getBanners', methods=['GET'])
def get_banner():
    try:
        # Get the container client inside the function
        container = database.get_container_client("BannerImgUrls")
        
        # Query to get all items from the container
        banners = list(container.read_all_items())
        
        # Return the data as JSON
        return jsonify(banners), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500      
@app.route('/removeBanner', methods=['POST'])
def remove_banner():
    try:
        # Get the container client
        container = database.get_container_client("BannerImgUrls")
        
        # Get the BannerId from the POST request body
        data = request.get_json()
        banner_id = data.get("BannerId")
        
        if not banner_id:
            return jsonify({"error": "BannerId is required"}), 400

        # Query to find the item based on the BannerId
        query = f"SELECT * FROM c WHERE c.BannerId = '{banner_id}'"
        items = list(container.query_items(query=query, enable_cross_partition_query=True))
        
        if not items:
            return jsonify({"error": "Banner not found"}), 404

        # Delete the item(s) based on BannerId
        for item in items:
            container.delete_item(item, partition_key=item['id'])

        return jsonify({"message": f"Banner with BannerId {banner_id} deleted successfully"}), 200
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
    
    # Ensure EventId is in the data
    if "EventId" not in data:
        return jsonify({"error": "EventId is required"}), 400
    data["id"] = generate_unique_id()
    data["status"] = "Scheduled"
    data["CreationDateTimeStamp"]= datetime.now().isoformat()
    container = database.get_container_client("EventMeta")
    # Query to check if a competition with the given EventId already exists
    query = "SELECT * FROM c WHERE c.EventId = @EventId"
    query_params = [
        {"name": "@EventId", "value": data["EventId"]}
    ]

    try:
        # Check if the competition already exists
        existing_items = list(container.query_items(
            query=query,
            parameters=query_params,
            enable_cross_partition_query=True
        ))
        if existing_items:
            # If the competition exists, replace it
            existing_item = existing_items[0]
            updated_item = container.replace_item(item=existing_item['id'], body=data)
            return jsonify({"eventId": data["EventId"]}), 200
        else:
            # If the competition does not exist, create a new one
            new_item = container.create_item(body=data)
            return jsonify({"eventId": data["EventId"]}), 201
    except exceptions.CosmosResourceNotFoundError:
        # Handle the case where the container or database does not exist
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        # Handle other Cosmos DB errors
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        # Handle any other exceptions
        return jsonify({"error": str(e)}), 500


@app.route('/updateTeams', methods=['POST'])
def createTeams():
    data = request.json
    # Ensure EventId is in the data
    if "EventId" not in data:
        return jsonify({"error": "EventId is required"}), 400
    # Generate a unique ID for the record (if necessary)
    data["id"] = generate_unique_id()
    data["CreationDateTimeStamp"]= datetime.now().isoformat()
    container = database.get_container_client("EventTeamsJudges")
    try:
        # Check if the record with the given EventId already exists
        query = "SELECT * FROM c WHERE c.EventId=@eventId"
        parameters = [{"name": "@eventId", "value": data["EventId"]}]
        existing_records = list(container.query_items(query=query, parameters=parameters, enable_cross_partition_query=True))
        if existing_records:
            # Record exists, update it
            existing_record = existing_records[0]
            # Update the existing record with new data
            container.replace_item(item=existing_record["id"], body=data)
            configureEventOrderMain(data) 
            return jsonify({"eventId": data["EventId"]}), 200
        else:
            # Record does not exist, create a new one
            container.create_item(body=data)
            configureEventOrderMain(data) 
            return jsonify({"eventId": data["EventId"]}), 201
    except exceptions.CosmosResourceNotFoundError:
        # Handle the case where the container or database does not exist
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        # Handle other Cosmos DB errors
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        # Handle any other exceptions
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
        
        # Define the scorecard access token document
        scorecardAccessTokens = {
            'id': generate_unique_id(),
            'EventId': data["EventId"],
            'judgeId': judge_id,
            'judgeName': judge_name,
            'HostAccess': False,
            'JudgeAccess': True,
            'CoachAccess': False,
            'TokenId': generate_token(),
            'CreationDateTimeStamp':datetime.now().isoformat()
        }

        # Query to check if token already exists for this judge and event
        query = "SELECT * FROM c WHERE c.EventId = @EventId AND c.judgeId = @judgeId"
        query_params = [
            {"name": "@EventId", "value": data["EventId"]},
            {"name": "@judgeId", "value": judge_id}
        ]

        try:
            # Check for existing tokens
            existing_tokens = list(accessTokenContainer.query_items(
                query=query,
                parameters=query_params,
                enable_cross_partition_query=True
            ))

            if existing_tokens:
                # If token exists, replace it
                existing_token = existing_tokens[0]
                scorecardAccessTokens['TokenId']=existing_token['TokenId']
                updated_token = accessTokenContainer.replace_item(item=existing_token['id'], body=scorecardAccessTokens)
                print(f"Updated access token for judge {judge_id}: {updated_token}")
            else:
                # If token does not exist, create a new one
                created_token = accessTokenContainer.create_item(body=scorecardAccessTokens)
                print(f"Created new access token for judge {judge_id}: {created_token}")
                
        except exceptions.CosmosHttpResponseError as e:
            # Log the error and continue; individual token creation or replacement failures should not stop the process
            print(f"Failed to process access token for judge {judge_id}: {e}")
        except Exception as e:
            # Handle unexpected errors
            print(f"Unexpected error for judge {judge_id}: {e}")


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
            'TokenId':generate_token(),
            'CreationDateTimeStamp':datetime.now().isoformat()
        }
        try: # Insert scorecard document into container
            accessTokenContainer.create_item(body=scorecardAccessTokens)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route('/CreateHostAccess', methods=['POST'])
def generateAccessTokensHostAccess():
    data=request.json
    HostConatiner = database.get_container_client("EventHostMeta")
    scorecardAccessTokens = {
        'id':generate_unique_id(),
        'HostId':generate_unique_id(),
        'Email':data['Email'],
        'CreationDateTimeStamp':datetime.now().isoformat()
    }
    accessTokenContainer = database.get_container_client("HostAccessRequests")
    try:
        # Insert scorecard document into container
        HostConatiner.create_item(body=scorecardAccessTokens)
        query = f"SELECT * FROM HostAccessRequests c WHERE c.Email = '{data['Email']}'"
        items = list(accessTokenContainer.query_items(query=query, enable_cross_partition_query=True))

        # If item(s) found, delete them
        for item in items:
            accessTokenContainer.delete_item(item=item['id'], partition_key=item['id'])
        
        return jsonify({"message": "Successfully Created Host Access"}), 200
        return jsonify({"message": "Successfully Created Host Access "}), 200
    except Exception as e:
        print("this is tyhe error"+e)
        return jsonify({"error": str(e)}), 500
import random
import string

def generate_code(length=6):
    characters = string.ascii_letters + string.digits
    code = ''.join(random.choice(characters) for _ in range(length))
    return code

# Example usage
print(generate_code(6))  # Generates a 6-character random code

CLIENT_ID = 'd7b1ed96-6e95-4354-af2a-544869f09e55'
CLIENT_SECRET = 'cfc8Q~2epL9FdAtlvwCEjwCmvrsJ-dDVKSj1Zclo'
TENANT_ID = 'eccdeba0-716d-4614-9824-ff4754cf84a9'
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["https://graph.microsoft.com/.default"]



# MSAL client instance
app_msal = ConfidentialClientApplication(
    CLIENT_ID,
    authority=AUTHORITY,
    client_credential=CLIENT_SECRET
)

GMAIL_USER = 'nandhasriramsabbina@gmail.com'
GMAIL_APP_PASSWORD = 'fngm ypaw glfo tgvo'

@app.route('/SentOtp', methods=['POST'])
def SentOtp():
    data = request.json
    emails = data['Email']
    recipient = emails
    subject = 'Email OTP Verification'
    html_content = read_html_content("emailInvite.html")
    otp = generate_code(6)
    
    # Save OTP to the database
    accessTokenContainer = database.get_container_client("OtpMeta")
    otpDoc = {
        'id': generate_unique_id(),
        'Email': data['Email'],
        'Otp': otp,
        'CreationDateTimeStamp': datetime.now().isoformat()
    }
    accessTokenContainer.create_item(body=otpDoc)
    
    # Format the email content with OTP
    html_content = format_html_content(html_content, otpDoc)
    layout = read_html_content("scorecardLayout.html")
    emailContent = {'mailContent': html_content}
    html_content = format_html_content(layout, emailContent)

    try:
        # Create the email message
        msg = MIMEMultipart()
        msg['From'] = GMAIL_USER
        msg['To'] = recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(html_content, 'html'))
        
        # Connect to Gmail's SMTP server
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()  # Upgrade the connection to secure
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, recipient, msg.as_string())
        
        return jsonify({'message': 'Email sent successfully'})
    except Exception as e:
        return jsonify({'error': str(e)})
    
@app.route('/OtpVerification', methods=['POST'])
def OtpVerification():
    data=request.json
    otpContainer = database.get_container_client("OtpMeta")
    try:
        validationQuery = f"SELECT * FROM c WHERE c.Email = '{data['Email']}' AND c.Otp = '{data['OTP_CODE']}'"
        Tokens = list(otpContainer.query_items(query=validationQuery, enable_cross_partition_query=True))
        if(len(Tokens)>0):
            result={'validation':'true'}
        else:
            result={'validation':'false'}
        return jsonify(result), 200
        # Insert scorecard document into container
    except Exception as e:
        return jsonify({"error": str(e)}), 500   
# Define the function to delete old OTP entries
# def delete_old_otps():
#     ten_minutes_ago = datetime.now() - timedelta(minutes=10)
#     query = "SELECT * FROM c WHERE c.CreationDateTimeStamp < @timestamp"
#     parameters = [{'name': '@timestamp', 'value': ten_minutes_ago.isoformat()}]
#     otpContainer = database.get_container_client("OtpMeta")
#     old_otps = otpContainer.query_items(query=query, parameters=parameters, enable_cross_partition_query=True)
#     for otp in old_otps:
#         otpContainer.delete_item(item=otp, partition_key=otp['id'])

# # Setup APScheduler to run the delete_old_otps function every minute
# scheduler = BackgroundScheduler()
# scheduler.add_job(delete_old_otps, 'interval', minutes=1)
# scheduler.start()     
@app.route('/createLoginDetails', methods=['POST'])
def createAccount():
    data=request.json
    accessTokenContainer = database.get_container_client("EventAuthKeys")
    scorecardAccessTokens = {
        'id':generate_unique_id(),
        'Email':data['Email'],
        'Password':data['Password'],
        'CreationDateTimeStamp':datetime.now().isoformat()
    }
    try:
        # Insert scorecard document into container
        accessTokenContainer.create_item(body=scorecardAccessTokens)
        if(data['HostAccessRequest']=='true'):
            RequestContainer = database.get_container_client("HostAccessRequests")
            RequestContainer.create_item(body=scorecardAccessTokens)
        return jsonify({"message": "Successfully Created Account "}), 200
    except Exception as e:
        print("this is tyhe error"+e)
        return jsonify({"error": str(e)}), 500

@app.route('/approveHostAccess', methods=['POST'])
def approveHostAccess():
    data=request.json
    result={}
    accessTokenContainer = database.get_container_client("HostAccessRequests")
    try:
        container = database.get_container_client("EventMeta")
        query = "SELECT * FROM c"
        items = accessTokenContainer.query_items(query=query, enable_cross_partition_query=True)
        result = list(items)
        return jsonify(result), 200
        # Insert scorecard document into container
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/authLoginDetails', methods=['POST'])
def authLoginDetails():
    data=request.json
    result={}
    accessTokenContainer = database.get_container_client("EventAuthKeys")
    try:
        validationQuery = f"SELECT * FROM c WHERE c.Email = '{data['Email']}' AND c.Password = '{data['Password']}'"
        Tokens = list(accessTokenContainer.query_items(query=validationQuery, enable_cross_partition_query=True))
        if(len(Tokens)>0):
            accessTokenContainer = database.get_container_client("EventHostMeta")
            validationQuery = f"SELECT * FROM c WHERE c.Email = '{data['Email']}'"
            access=list(accessTokenContainer.query_items(query=validationQuery, enable_cross_partition_query=True))
            if(len(access)>0):
                result={'validation':'true','HostAccess':'true','HostId':access[0]['HostId'],'OwnerAccess':'true' if data['Email'] == 'nandhashriramsabbina@outlook.com' else 'false'}
            else:
                result={'validation':'true','HostAccess':'false','OwnerAccess':'true' if data['Email'] == 'nandhashriramsabbina@outlook.com' else 'false'}    
        else:
            result={'validation':'false','HostAccess':'false','OwnerAccess':'true' if data['Email'] == 'nandhashriramsabbina@outlook.com' else 'false'}
        return jsonify(result), 200
        # Insert scorecard document into container
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
    
#saveScoreParameters   

@app.route('/saveScoreParameters', methods=['POST'])
def update_Scorecard():
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
    
@app.route('/getBanners', methods=['GET'])
def getBanners():
    try:
        container = database.get_container_client("BannerImgUrls")
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
    
def get_category_entry(scorecardMeta, category_name):
    return next((entry for entry in scorecardMeta if entry['category'] == category_name), None)

def add_scorecard(data):
    competition_id = data.get('EventId')

    # Initialize Cosmos Client
    container = database.get_container_client("EventMeta")
    query = f"SELECT c.eventCategory, c.scorecardMeta FROM c WHERE c.EventId = '{competition_id}'"

    try:
        # Fetch event category and scorecard meta
        items = container.query_items(query=query, enable_cross_partition_query=True)
        eventCategorys = list(items)
        if not eventCategorys:
            return jsonify({"error": "No event category found for the given EventId"}), 404

        eventCategorys = eventCategorys[0]
        eventScoreCardMeta = eventCategorys.get('scorecardMeta', [])
        eventCategorys = eventCategorys.get('eventCategory', [])

        # Initialize the scorecard container client
        scorecard_container = database.get_container_client("EventScoreCard")

        # Create scorecard entry for every judge * team combination
        for category in eventCategorys:
            for judge in data.get('JudegsInfo', []):
                judge_id = judge.get('id')
                judge_name = judge.get('name')
                for team in data.get('teamsInfo', []):
                    team_id = team.get('teamName', {}).get('id')
                    team_name = team.get('teamName', {}).get('name')

                    # Check for existing scorecard
                    unique_query = f"SELECT c.id FROM c WHERE c.EventId = '{data['EventId']}' AND c.judgeId = '{judge_id}' AND c.teamId = '{team_id}' AND c.category = '{category}'"
                    existing_entries = list(scorecard_container.query_items(query=unique_query, enable_cross_partition_query=True))

                    if existing_entries:
                        # Skip creating the entry if it already exists
                        continue

                    # Initialize scorecard with dynamic fields based on scorecardMeta
                    scorecard = {param['name']: 0 for param in get_category_entry(eventScoreCardMeta, category).get('parameters', [])}
                    scorecard['total'] = 0  # Initialize total score

                    # Create initial scorecard document
                    scorecard_document = {
                        'id': generate_unique_id(),
                        'EventId': data["EventId"],
                        'judgeId': judge_id,
                        'judgeName': judge_name,
                        'teamId': team_id,
                        'teamName': team_name,
                        'category': category,
                        'teamMemberId': None,  # Assuming we don't have specific team member ID here
                        'scorecard': scorecard,
                        'comments': '',
                        'CreationDateTimeStamp': datetime.now().isoformat()
                    }

                    # Insert scorecard document into container
                    try:
                        scorecard_container.create_item(body=scorecard_document)
                    except Exception as e:
                        return jsonify({"error": str(e)}), 500

        return jsonify({"status": "Scorecards created successfully"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/update_scores', methods=['POST'])
def update_scores():
    try:
        data = request.json
        scorecard_id=data["id"]
        eventId=data["EventId"]
        new_scores=data["scorecard"]
        comments=data["comment"]
        scorecard_container = database.get_container_client("EventScoreCard")
        # Retrieve the scorecard document from the database
        scorecard_document = scorecard_container.read_item(item=scorecard_id,partition_key=eventId)
        # Update the scores in the scorecard document
        scorecard_document['scorecard'].update(new_scores)
        scorecard_document['comments']=comments
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
        category=data.get('category')
        if not competition_id or not judge_id:
            return jsonify({"error": "Please provide both competitionId and judgeId in the request body"}), 400
        scorecard_container = database.get_container_client("EventScoreCard")
            # Query scorecards for the given competition_id and judge_id
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}' AND c.judgeId = '{judge_id}' AND c.teamId='{teamId}' AND c.category='{category}'"
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
        competition_id = data.get('EventId')

        # Initialize Cosmos DB container
        scorecard_container = database.get_container_client("EventScoreCard")
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
        scorecards = list(scorecard_container.query_items(query=query, enable_cross_partition_query=True))

        # Initialize dictionary to store scores per category
        category_scores = {}

        # Process each scorecard entry
        for scorecard in scorecards:
            team_id = scorecard.get('teamId')
            team_name = scorecard.get('teamName')
            category = scorecard.get('category')
            scorecard_data = scorecard.get('scorecard', {})

            # Compute score dynamically, excluding 'total'
            score_fields = [key for key in scorecard_data if key != 'total']
            score = sum(scorecard_data.get(field, 0) for field in score_fields)

            # Create a unique key for each team per category
            team_category_key = (team_name, category)

            if category not in category_scores:
                category_scores[category] = {}

            if team_category_key not in category_scores[category]:
                category_scores[category][team_category_key] = {
                    'teamId': team_id,
                    'teamName': team_name,
                    'category': category,
                    'total_score': 0
                }

            category_scores[category][team_category_key]['total_score'] += score

        # Prepare leaderboard sorted by categories and scores
        leaderboard = {}
        for category, scores in category_scores.items():
            sorted_scores = sorted(scores.values(), key=lambda x: x['total_score'], reverse=True)
            leaderboard[category] = sorted_scores

        return jsonify({"leaderboard": leaderboard}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


OUTLOOK_USER='nandhashriramsabbina@outlook.com'
OUTLOOK_PASSWORD='eakwnysdkybugfuh'  # Use App Password if 2-Step Verification is enabled
def read_html_content(file_path):
    with open(file_path, 'r') as file:
        return file.read()

@app.route('/send-email', methods=['POST'])
def send_email():
    data=request.json
    emails = data['emails']
    recipient = ', '.join(emails)
    recipient=recipient.split(",")
    subject = 'Test'
    html_content = read_html_content("emailInvite.html")
    formatted_html = format_html_content(html_content, entry)
    html_content.replace("PLACEHOLDER_COMPANY_NAME","Productions")
    html_content.replace("PLACEHOLDER_EVENT_TITLE","Productions")
    try:
        # Create the email message
        msg = MIMEMultipart()
        msg['From'] = GMAIL_USER
        msg['To'] = recipient
        msg['Subject'] = subject
        layout = read_html_content("scorecardLayout.html")
        emailContent={'mailContent':html_content}
        html_content = format_html_content(layout, emailContent)
        msg.attach(MIMEText(html_content, 'html'))
        # Connect to Gmail's SMTP server
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()  # Upgrade the connection to secure
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, recipient, msg.as_string())
    except Exception as e:
            print( jsonify({'error': str(e)}))
    return jsonify({'message': 'Email sent successfully with PDF attachment'})
def format_html_content(template, data):
    for key, value in data.items():
        placeholder = '{{' + key + '}}'
        template = template.replace(placeholder, str(value))
    return template



@app.route('/send-scorecard', methods=['POST'])
def sendScoreCardsemail():
    data=request.json
    pdf_filename="ScoreCard.pdf"
    competition_id=data['EventId']
    container = database.get_container_client("EventMeta")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    items = container.query_items(query=query, enable_cross_partition_query=True)
    metaData = list(items)
    metaData=metaData[0]
    container = database.get_container_client("EventTeamsJudges")
    query=f"SELECT *  FROM c WHERE c.EventId = '{competition_id}' "
    emailsData = list(container.query_items(query=query, enable_cross_partition_query=True))
    # Extract emails
    emails = []
    scorecard_container = database.get_container_client("EventScoreCard")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    scorecards = list(scorecard_container.query_items(query=query, enable_cross_partition_query=True))
    for entry in scorecards:
        subject="Score Card by "+entry['judgeName']+' for '+entry['category']
        entry['titleHeading']="Score Card For "+entry['category']
        entry['eventTitle']=metaData['eventTitle']
        for iteam in entry['scorecard']:
            entry[iteam]=entry['scorecard'][iteam]
        html_content = read_html_content("ScoreCard.html")
        formatted_html = format_html_content(html_content, entry)
        specific_team_id = entry['teamId']
        emails = []
        for event in emailsData:
            for team in event.get('teamsInfo', []):
                if team['teamName']['id'] == specific_team_id:
                    if team['teamRepresentativeEmail']['email']:
                        emails.append(team['teamRepresentativeEmail']['email'])
                    if team['coachName']['email']:
                        emails.append(team['coachName']['email'])
                    if team['DirectorName']['email']:
                        emails.append(team['DirectorName']['email'])
        createScoreCardPdf(entry['judgeName']+'_ScoreCard.pdf',entry)
        emails = list(filter(None, set(emails)))
        recipient = ', '.join(emails)
        recipient=recipient.split(",")
        for entry in recipient:
            try:
                # Create the email message
                msg = MIMEMultipart()
                msg['From'] = GMAIL_USER
                msg['To'] = entry
                msg['Subject'] = subject
                layout = read_html_content("scorecardLayout.html")
                emailContent={'mailContent':formatted_html}
                html_content = format_html_content(layout, emailContent)
                msg.attach(MIMEText(html_content, 'html'))

                with open(pdf_filename, 'rb') as pdf_file:
                    pdf_attachment = MIMEApplication(pdf_file.read(), _subtype='pdf')
                    pdf_attachment.add_header('Content-Disposition', 'attachment', filename=pdf_filename)
                    msg.attach(pdf_attachment)
                # Connect to Gmail's SMTP server
                with smtplib.SMTP('smtp.gmail.com', 587) as server:
                    server.starttls()  # Upgrade the connection to secure
                    server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                    server.sendmail(GMAIL_USER, recipient, msg.as_string())
            except Exception as e:
                return jsonify({'error': str(e)})
    return jsonify({'message': "success"})
def configureEventOrder(data):
    competition_id = data['EventId']
    scorecard_container = database.get_container_client("EventScoreCard")
    # Query scorecards for the given competition_id
    query = f"SELECT c.category, c.teamId, c.teamName FROM c WHERE c.EventId = @EventId"
    query_params = [{"name": "@EventId", "value": competition_id}]
    listPerformances = list(scorecard_container.query_items(
        query=query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))

    eventOrder_document = {
        "id": generate_unique_id(),
        "EventId": competition_id,
        "categoryOrder": []
    }

    seen = set()
    unique_listPerformances = []
    for performance in listPerformances:
        identifier = (performance['category'], performance['teamId'], performance['teamName'])
        if identifier not in seen:
            seen.add(identifier)
            unique_listPerformances.append(performance)

    # Organize performances by category
    categories = {}
    for performance in unique_listPerformances:
        category = performance.get("category")
        team_id = performance.get("teamId")
        team_name = performance.get("teamName")

        if category not in categories:
            categories[category] = []

        categories[category].append({
            "teamId": team_id,
            "teamName": team_name,
        })

    for category_index, (category, teams) in enumerate(categories.items(), start=1):
        eventOrder_document["categoryOrder"].append({
            "category": category,
            "order": category_index,
            "performances": []
        })

        for team_index, team in enumerate(teams, start=1):
            team_with_order = team.copy()
            team_with_order["order"] = team_index
            eventOrder_document["categoryOrder"][-1]["performances"].append(team_with_order)

    # Container for EventOrderConfig
    Ordercontainer = database.get_container_client("EventOrderConfig")
    
    try:
        # Check if the event order document already exists
        existing_documents = list(Ordercontainer.query_items(
            query="SELECT * FROM c WHERE c.EventId = @EventId",
            parameters=query_params,
            enable_cross_partition_query=True
        ))

        if existing_documents:
            # If exists, replace the document
            existing_document = existing_documents[0]
            updated_document = Ordercontainer.replace_item(item=existing_document['id'], body=eventOrder_document)
            return jsonify(updated_document), 200
        else:
            # If does not exist, create a new document
            eventOrder_document["CreationDateTimeStamp"]=datetime.now().isoformat()
            new_document = Ordercontainer.create_item(body=eventOrder_document)
            return jsonify(new_document), 201

    except exceptions.CosmosResourceNotFoundError:
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
def configureEventOrderMain(data):
    competition_id = data['EventId']
    container = database.get_container_client("EventTeamsJudges")
    meta_conatiner = database.get_container_client("EventMeta")
    # Query scorecards for the given competition_id
    query = f"SELECT c.teamsInfo FROM c WHERE c.EventId = @EventId"
    category_query=f"SELECT c.eventCategory FROM c WHERE c.EventId = @EventId"
    query_params = [{"name": "@EventId", "value": competition_id}]
    listCategory = list(meta_conatiner.query_items(
        query=category_query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))
    listPerformances = list(container.query_items(
        query=query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))

    eventOrder_document = {
        "id": generate_unique_id(),
        "EventId": competition_id,
        "categoryOrder": []
    }

    seen = set()
    unique_listPerformances = []
    for category in listCategory[0]['eventCategory']:
        for performance in listPerformances[0]['teamsInfo']:
            identifier = (category, performance['teamName']['id'], performance['teamName']['name'])
            data = {
            'category': category,
            'teamId': performance['teamName']['id'],
            'teamName': performance['teamName']['name']
            }
            if identifier not in seen:
                seen.add(identifier)
                unique_listPerformances.append(data)

    # Organize performances by category
    categories = {}
    for performance in unique_listPerformances:
        category = performance.get("category")
        team_id = performance.get("teamId")
        team_name = performance.get("teamName")

        if category not in categories:
            categories[category] = []

        categories[category].append({
            "teamId": team_id,
            "teamName": team_name,
        })

    for category_index, (category, teams) in enumerate(categories.items(), start=1):
        eventOrder_document["categoryOrder"].append({
            "category": category,
            "order": category_index,
            "performances": []
        })

        for team_index, team in enumerate(teams, start=1):
            team_with_order = team.copy()
            team_with_order["order"] = team_index
            eventOrder_document["categoryOrder"][-1]["performances"].append(team_with_order)

    # Container for EventOrderConfig
    Ordercontainer = database.get_container_client("EventOrderConfig")
    
    try:
        # Check if the event order document already exists
        existing_documents = list(Ordercontainer.query_items(
            query="SELECT * FROM c WHERE c.EventId = @EventId",
            parameters=query_params,
            enable_cross_partition_query=True
        ))

        if existing_documents:
            # If exists, replace the document
            existing_document = existing_documents[0]
            updated_document = Ordercontainer.replace_item(item=existing_document['id'], body=eventOrder_document)
            return jsonify(updated_document), 200
        else:
            # If does not exist, create a new document
            eventOrder_document["CreationDateTimeStamp"]=datetime.now().isoformat()
            new_document = Ordercontainer.create_item(body=eventOrder_document)
            return jsonify(new_document), 201

    except exceptions.CosmosResourceNotFoundError:
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500        
@app.route('/getEventOrder', methods=['POST'])
def getEventOrder():
    Ordercontainer = database.get_container_client("EventOrderConfig")
    data=request.json
    competition_id=data['EventId']
    try:
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
        eventOrder_document = list(Ordercontainer.query_items(query=query, enable_cross_partition_query=True))
        return  eventOrder_document[0], 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route('/updateEventOrder', methods=['POST'])
def updateEventOrder():
    Ordercontainer = database.get_container_client("EventOrderConfig")
    data=request.json
    competition_id=data['EventId']
    order_id=data['id']
    try:
        updated_document = Ordercontainer.replace_item(item=order_id, body=data)
        return  updated_document, 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
def createScoreCardPdf(filename,data):
    try:
        doc = SimpleDocTemplate(filename, pagesize=letter)
        styles = getSampleStyleSheet()
        elements = []

        # Title
        title_style = styles['Title']
        title_style.fontName = 'Helvetica-Bold'
        title_style.fontSize = 24
        title_style.alignment = TA_CENTER
        title = Paragraph("Score Card", title_style)
        elements.append(title)
        elements.append(Spacer(1, 0.5 * inch))

        for entry in data:
            # Event Title
            event_title_style = styles['Heading1']
            event_title_style.fontName = 'Helvetica-Bold'
            event_title_style.fontSize = 20
            event_title_style.alignment = TA_CENTER
            event_title = Paragraph(f"{entry['eventTitle']}", event_title_style)
            elements.append(event_title)
            elements.append(Spacer(1, 0.25 * inch))

            # Judge and Team Details
            details_style = styles['Normal']
            details_style.fontName = 'Helvetica'
            details_style.fontSize = 12
            details_style.alignment = TA_LEFT
            judge_name = Paragraph(f"<b>Judge:</b> {entry['judgeName']}", details_style)
            team_name = Paragraph(f"<b>Team:</b> {entry['teamName']}", details_style)
            comments = Paragraph(f"<b>Comments:</b> {entry['Comments']}", details_style)
            elements.append(judge_name)
            elements.append(team_name)
            elements.append(comments)
            elements.append(Spacer(1, 0.5 * inch))

            # Performance Table
            table_data = [
                ["Category", "Score"],
                ["Creativity", entry['creativity']],
                ["Difficulty", entry['difficulty']],
                ["Formation", entry['formation']],
                ["Sync", entry['sync']],
                ["Technique", entry['technique']],
                ["Total", entry['total']]
            ]

            table = Table(table_data, colWidths=[2.5 * inch, 1.5 * inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4CAF50')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 0.5 * inch))

        # Build PDF
        doc.build(elements)
    except Exception as e:
         print(jsonify({"error": str(e)}), 500)


def create_pdf(filename, data,eventOrder):
    doc = SimpleDocTemplate(filename, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    title = Paragraph("Event Schedule", styles['Title'])
    elements.append(title)
    elements.append(Paragraph("<br/>", styles['Normal']))

    # Event Title
    event_id = Paragraph(f"{data.get('eventTitle', '')}", styles['Normal'])
    elements.append(event_id)
    elements.append(Paragraph("<br/>", styles['Normal']))
    # Event Venue String
    event_id = Paragraph(f"Venue :{data.get('eventVenue', '')}", styles['Normal'])
    elements.append(event_id)
    elements.append(Paragraph("<br/>", styles['Normal']))
    # Event Data String
    event_id = Paragraph(f"Date and Time :{data.get('eventDateString', '')}", styles['Normal'])
    elements.append(event_id)
    elements.append(Paragraph("<br/>", styles['Normal']))

    # Categories and Performances
    for category in eventOrder['categoryOrder']:
        category_title = Paragraph(f"<b>Category: {category['category']} (Order: {category['order']})</b>", styles['Heading2'])
        elements.append(category_title)
        # Table Data
        table_data = [["Order", "Team Name"]]  # Removed "Team ID"
        for performance in category['performances']:
            table_data.append([performance['order'], performance['teamName']])  # Removed "Team ID"
        # Create Table
        table = Table(table_data, colWidths=[1 * inch, 2.5 * inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 1, black),
        ]))
        elements.append(table)
        elements.append(Paragraph("<br/>", styles['Normal']))

    # Build PDF
    doc.build(elements)

# Route to send email with PDF attachment
@app.route('/sendEventSchedule', methods=['POST'])
def send_email_with_pdf():
    data = request.json
    competition_id = data.get('EventId')
    # Initialize Cosmos Client
    container = database.get_container_client("EventMeta")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    items = container.query_items(query=query, enable_cross_partition_query=True)
    eventCategorys = list(items)
    data=eventCategorys[0]
    query=f"SELECT *  FROM c WHERE c.EventId = '{competition_id}' "
    subject = (data.get('eventTitle', '') + '|' +
           data.get('eventDateString', '') + '|' +
           data.get('eventVenue', '') + ' Schedule')    # Create the PDF
    Ordercontainer = database.get_container_client("EventOrderConfig")
    competition_id=data['EventId']
    container = database.get_container_client("EventTeamsJudges")
    emailsData = list(container.query_items(query=query, enable_cross_partition_query=True))
    # Extract emails
    emails = []

# Extract team representative, coach, and director emails
    for event in emailsData:
        for team in event.get('teamsInfo', []):
            if team['teamRepresentativeEmail']['email']:
                emails.append(team['teamRepresentativeEmail']['email'])
            if team['coachName']['email']:
                emails.append(team['coachName']['email'])
            if team['DirectorName']['email']:
                emails.append(team['DirectorName']['email'])
    # Remove empty strings (if any) and duplicates
    emails = list(filter(None, set(emails)))
    recipient = ','.join(emails)
    recipient=recipient.split(",")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    eventOrder_document = list(Ordercontainer.query_items(query=query, enable_cross_partition_query=True))
    #create_pdf(pdf_filename, data,eventOrder_document[0])
    # Read and format HTML content
    firsthtml = read_html_content("EventSchedule-converted.html")
    firsthtml=format_html_content(firsthtml, data)
    for category in eventOrder_document[0]['categoryOrder']:
        html_content = read_html_content("categoryEventTag.html")
        tagData={}
        tagData['Category']=category['category']
        # Table Data
        table_data = [["Order", "Team Name"]]  # Removed "Team ID"
        orderTags=''
        for performance in category['performances']:
            perData={}
            entryTag = read_html_content("orderandTeamTag.html")
            perData['order']=performance['order']
            perData['TeamName']=performance['teamName']
            orderTags=orderTags+format_html_content(entryTag, perData)
        tagData['orderTags']  = orderTags
        firsthtml = firsthtml+format_html_content(html_content, tagData)
    firsthtml=firsthtml+read_html_content("EventScheduleEnd.html")
    for entry in recipient:
        try:
            # Create the email message
            msg = MIMEMultipart()
            msg['From'] = GMAIL_USER
            msg['To'] = entry
            msg['Subject'] = subject
            layout = read_html_content("scorecardLayout.html")
            emailContent={'mailContent':firsthtml}
            html_content = format_html_content(layout, emailContent)
            msg.attach(MIMEText(html_content, 'html'))


            # Connect to Gmail's SMTP server
            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.starttls()  # Upgrade the connection to secure
                server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                server.sendmail(GMAIL_USER, recipient, msg.as_string())
            # Clean up
        except Exception as e:
            print( jsonify({'error': str(e)}))
    return jsonify({'message': 'Email sent successfully with PDF attachment'})
        
if __name__ == "__main__":
    app.run(host="0.0.0.0",port=5001)



@app.route('/getBanners', methods=['GET'])
def get_banner():
    try:
        # Get the container client inside the function
        container = database.get_container_client("BannerImgUrls")
        
        # Query to get all items from the container
        banners = list(container.read_all_items())
        
        # Return the data as JSON
        return jsonify(banners), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500      
@app.route('/removeBanner', methods=['POST'])
def remove_banner():
    try:
        # Get the container client
        container = database.get_container_client("BannerImgUrls")
        
        # Get the BannerId from the POST request body
        data = request.get_json()
        banner_id = data.get("BannerId")
        
        if not banner_id:
            return jsonify({"error": "BannerId is required"}), 400

        # Query to find the item based on the BannerId
        query = f"SELECT * FROM c WHERE c.BannerId = '{banner_id}'"
        items = list(container.query_items(query=query, enable_cross_partition_query=True))
        
        if not items:
            return jsonify({"error": "Banner not found"}), 404

        # Delete the item(s) based on BannerId
        for item in items:
            container.delete_item(item, partition_key=item['id'])

        return jsonify({"message": f"Banner with BannerId {banner_id} deleted successfully"}), 200
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
    
    # Ensure EventId is in the data
    if "EventId" not in data:
        return jsonify({"error": "EventId is required"}), 400
    data["id"] = generate_unique_id()
    data["status"] = "Scheduled"
    data["CreationDateTimeStamp"]= datetime.now().isoformat()
    container = database.get_container_client("EventMeta")
    # Query to check if a competition with the given EventId already exists
    query = "SELECT * FROM c WHERE c.EventId = @EventId"
    query_params = [
        {"name": "@EventId", "value": data["EventId"]}
    ]

    try:
        # Check if the competition already exists
        existing_items = list(container.query_items(
            query=query,
            parameters=query_params,
            enable_cross_partition_query=True
        ))
        if existing_items:
            # If the competition exists, replace it
            existing_item = existing_items[0]
            updated_item = container.replace_item(item=existing_item['id'], body=data)
            return jsonify({"eventId": data["EventId"]}), 200
        else:
            # If the competition does not exist, create a new one
            new_item = container.create_item(body=data)
            return jsonify({"eventId": data["EventId"]}), 201
    except exceptions.CosmosResourceNotFoundError:
        # Handle the case where the container or database does not exist
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        # Handle other Cosmos DB errors
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        # Handle any other exceptions
        return jsonify({"error": str(e)}), 500


@app.route('/updateTeams', methods=['POST'])
def createTeams():
    data = request.json
    # Ensure EventId is in the data
    if "EventId" not in data:
        return jsonify({"error": "EventId is required"}), 400
    # Generate a unique ID for the record (if necessary)
    data["id"] = generate_unique_id()
    data["CreationDateTimeStamp"]= datetime.now().isoformat()
    container = database.get_container_client("EventTeamsJudges")
    try:
        # Check if the record with the given EventId already exists
        query = "SELECT * FROM c WHERE c.EventId=@eventId"
        parameters = [{"name": "@eventId", "value": data["EventId"]}]
        existing_records = list(container.query_items(query=query, parameters=parameters, enable_cross_partition_query=True))
        if existing_records:
            # Record exists, update it
            existing_record = existing_records[0]
            # Update the existing record with new data
            container.replace_item(item=existing_record["id"], body=data)
            configureEventOrderMain(data) 
            return jsonify({"eventId": data["EventId"]}), 200
        else:
            # Record does not exist, create a new one
            container.create_item(body=data)
            configureEventOrderMain(data) 
            return jsonify({"eventId": data["EventId"]}), 201
    except exceptions.CosmosResourceNotFoundError:
        # Handle the case where the container or database does not exist
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        # Handle other Cosmos DB errors
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        # Handle any other exceptions
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
        
        # Define the scorecard access token document
        scorecardAccessTokens = {
            'id': generate_unique_id(),
            'EventId': data["EventId"],
            'judgeId': judge_id,
            'judgeName': judge_name,
            'HostAccess': False,
            'JudgeAccess': True,
            'CoachAccess': False,
            'TokenId': generate_token(),
            'CreationDateTimeStamp':datetime.now().isoformat()
        }

        # Query to check if token already exists for this judge and event
        query = "SELECT * FROM c WHERE c.EventId = @EventId AND c.judgeId = @judgeId"
        query_params = [
            {"name": "@EventId", "value": data["EventId"]},
            {"name": "@judgeId", "value": judge_id}
        ]

        try:
            # Check for existing tokens
            existing_tokens = list(accessTokenContainer.query_items(
                query=query,
                parameters=query_params,
                enable_cross_partition_query=True
            ))

            if existing_tokens:
                # If token exists, replace it
                existing_token = existing_tokens[0]
                scorecardAccessTokens['TokenId']=existing_token['TokenId']
                updated_token = accessTokenContainer.replace_item(item=existing_token['id'], body=scorecardAccessTokens)
                print(f"Updated access token for judge {judge_id}: {updated_token}")
            else:
                # If token does not exist, create a new one
                created_token = accessTokenContainer.create_item(body=scorecardAccessTokens)
                print(f"Created new access token for judge {judge_id}: {created_token}")
                
        except exceptions.CosmosHttpResponseError as e:
            # Log the error and continue; individual token creation or replacement failures should not stop the process
            print(f"Failed to process access token for judge {judge_id}: {e}")
        except Exception as e:
            # Handle unexpected errors
            print(f"Unexpected error for judge {judge_id}: {e}")


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
            'TokenId':generate_token(),
            'CreationDateTimeStamp':datetime.now().isoformat()
        }
        try: # Insert scorecard document into container
            accessTokenContainer.create_item(body=scorecardAccessTokens)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route('/CreateHostAccess', methods=['POST'])
def generateAccessTokensHostAccess():
    data=request.json
    HostConatiner = database.get_container_client("EventHostMeta")
    scorecardAccessTokens = {
        'id':generate_unique_id(),
        'HostId':generate_unique_id(),
        'Email':data['Email'],
        'CreationDateTimeStamp':datetime.now().isoformat()
    }
    accessTokenContainer = database.get_container_client("HostAccessRequests")
    try:
        # Insert scorecard document into container
        HostConatiner.create_item(body=scorecardAccessTokens)
        query = f"SELECT * FROM HostAccessRequests c WHERE c.Email = '{data['Email']}'"
        items = list(accessTokenContainer.query_items(query=query, enable_cross_partition_query=True))

        # If item(s) found, delete them
        for item in items:
            accessTokenContainer.delete_item(item=item['id'], partition_key=item['id'])
        
        return jsonify({"message": "Successfully Created Host Access"}), 200
        return jsonify({"message": "Successfully Created Host Access "}), 200
    except Exception as e:
        print("this is tyhe error"+e)
        return jsonify({"error": str(e)}), 500
import random
import string

def generate_code(length=6):
    characters = string.ascii_letters + string.digits
    code = ''.join(random.choice(characters) for _ in range(length))
    return code

# Example usage
print(generate_code(6))  # Generates a 6-character random code

CLIENT_ID = 'd7b1ed96-6e95-4354-af2a-544869f09e55'
CLIENT_SECRET = 'cfc8Q~2epL9FdAtlvwCEjwCmvrsJ-dDVKSj1Zclo'
TENANT_ID = 'eccdeba0-716d-4614-9824-ff4754cf84a9'
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["https://graph.microsoft.com/.default"]



# MSAL client instance
app_msal = ConfidentialClientApplication(
    CLIENT_ID,
    authority=AUTHORITY,
    client_credential=CLIENT_SECRET
)

GMAIL_USER = 'nandhasriramsabbina@gmail.com'
GMAIL_APP_PASSWORD = 'fngm ypaw glfo tgvo'

@app.route('/SentOtp', methods=['POST'])
def SentOtp():
    data = request.json
    emails = data['Email']
    recipient = emails
    subject = 'Email OTP Verification'
    html_content = read_html_content("emailInvite.html")
    otp = generate_code(6)
    
    # Save OTP to the database
    accessTokenContainer = database.get_container_client("OtpMeta")
    otpDoc = {
        'id': generate_unique_id(),
        'Email': data['Email'],
        'Otp': otp,
        'CreationDateTimeStamp': datetime.now().isoformat()
    }
    accessTokenContainer.create_item(body=otpDoc)
    
    # Format the email content with OTP
    html_content = format_html_content(html_content, otpDoc)
    layout = read_html_content("scorecardLayout.html")
    emailContent = {'mailContent': html_content}
    html_content = format_html_content(layout, emailContent)

    try:
        # Create the email message
        msg = MIMEMultipart()
        msg['From'] = GMAIL_USER
        msg['To'] = recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(html_content, 'html'))
        
        # Connect to Gmail's SMTP server
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()  # Upgrade the connection to secure
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, recipient, msg.as_string())
        
        return jsonify({'message': 'Email sent successfully'})
    except Exception as e:
        return jsonify({'error': str(e)})
    
@app.route('/OtpVerification', methods=['POST'])
def OtpVerification():
    data=request.json
    otpContainer = database.get_container_client("OtpMeta")
    try:
        validationQuery = f"SELECT * FROM c WHERE c.Email = '{data['Email']}' AND c.Otp = '{data['OTP_CODE']}'"
        Tokens = list(otpContainer.query_items(query=validationQuery, enable_cross_partition_query=True))
        if(len(Tokens)>0):
            result={'validation':'true'}
        else:
            result={'validation':'false'}
        return jsonify(result), 200
        # Insert scorecard document into container
    except Exception as e:
        return jsonify({"error": str(e)}), 500   
# Define the function to delete old OTP entries
# def delete_old_otps():
#     ten_minutes_ago = datetime.now() - timedelta(minutes=10)
#     query = "SELECT * FROM c WHERE c.CreationDateTimeStamp < @timestamp"
#     parameters = [{'name': '@timestamp', 'value': ten_minutes_ago.isoformat()}]
#     otpContainer = database.get_container_client("OtpMeta")
#     old_otps = otpContainer.query_items(query=query, parameters=parameters, enable_cross_partition_query=True)
#     for otp in old_otps:
#         otpContainer.delete_item(item=otp, partition_key=otp['id'])

# # Setup APScheduler to run the delete_old_otps function every minute
# scheduler = BackgroundScheduler()
# scheduler.add_job(delete_old_otps, 'interval', minutes=1)
# scheduler.start()     
@app.route('/createLoginDetails', methods=['POST'])
def createAccount():
    data=request.json
    accessTokenContainer = database.get_container_client("EventAuthKeys")
    scorecardAccessTokens = {
        'id':generate_unique_id(),
        'Email':data['Email'],
        'Password':data['Password'],
        'CreationDateTimeStamp':datetime.now().isoformat()
    }
    try:
        # Insert scorecard document into container
        accessTokenContainer.create_item(body=scorecardAccessTokens)
        if(data['HostAccessRequest']=='true'):
            RequestContainer = database.get_container_client("HostAccessRequests")
            RequestContainer.create_item(body=scorecardAccessTokens)
        return jsonify({"message": "Successfully Created Account "}), 200
    except Exception as e:
        print("this is tyhe error"+e)
        return jsonify({"error": str(e)}), 500

@app.route('/approveHostAccess', methods=['POST'])
def approveHostAccess():
    data=request.json
    result={}
    accessTokenContainer = database.get_container_client("HostAccessRequests")
    try:
        container = database.get_container_client("EventMeta")
        query = "SELECT * FROM c"
        items = accessTokenContainer.query_items(query=query, enable_cross_partition_query=True)
        result = list(items)
        return jsonify(result), 200
        # Insert scorecard document into container
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/authLoginDetails', methods=['POST'])
def authLoginDetails():
    data=request.json
    result={}
    accessTokenContainer = database.get_container_client("EventAuthKeys")
    try:
        validationQuery = f"SELECT * FROM c WHERE c.Email = '{data['Email']}' AND c.Password = '{data['Password']}'"
        Tokens = list(accessTokenContainer.query_items(query=validationQuery, enable_cross_partition_query=True))
        if(len(Tokens)>0):
            accessTokenContainer = database.get_container_client("EventHostMeta")
            validationQuery = f"SELECT * FROM c WHERE c.Email = '{data['Email']}'"
            access=list(accessTokenContainer.query_items(query=validationQuery, enable_cross_partition_query=True))
            if(len(access)>0):
                result={'validation':'true','HostAccess':'true','HostId':access[0]['HostId'],'OwnerAccess':'true'  if data['Email'].lower() == 's3productionsllc@outlook.com'.lower() else 'false'}
            else:
                result={'validation':'true','HostAccess':'false','OwnerAccess':'true' if data['Email'].lower() == 's3productionsllc@outlook.com'.lower() else 'false'}    
        else:
            result={'validation':'false','HostAccess':'false','OwnerAccess':'true' if data['Email'].lower() == 's3productionsllc@outlook.com'.lower() else 'false'}
        return jsonify(result), 200
        # Insert scorecard document into container
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
    
#saveScoreParameters   

@app.route('/saveScoreParameters', methods=['POST'])
def update_Scorecard():
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
    
@app.route('/getBanners', methods=['GET'])
def getBanners():
    try:
        container = database.get_container_client("BannerImgUrls")
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
    
def get_category_entry(scorecardMeta, category_name):
    return next((entry for entry in scorecardMeta if entry['category'] == category_name), None)

def add_scorecard(data):
    competition_id = data.get('EventId')

    # Initialize Cosmos Client
    container = database.get_container_client("EventMeta")
    query = f"SELECT c.eventCategory, c.scorecardMeta FROM c WHERE c.EventId = '{competition_id}'"

    try:
        # Fetch event category and scorecard meta
        items = container.query_items(query=query, enable_cross_partition_query=True)
        eventCategorys = list(items)
        if not eventCategorys:
            return jsonify({"error": "No event category found for the given EventId"}), 404

        eventCategorys = eventCategorys[0]
        eventScoreCardMeta = eventCategorys.get('scorecardMeta', [])
        eventCategorys = eventCategorys.get('eventCategory', [])

        # Initialize the scorecard container client
        scorecard_container = database.get_container_client("EventScoreCard")

        # Create scorecard entry for every judge * team combination
        for category in eventCategorys:
            for judge in data.get('JudegsInfo', []):
                judge_id = judge.get('id')
                judge_name = judge.get('name')
                for team in data.get('teamsInfo', []):
                    team_id = team.get('teamName', {}).get('id')
                    team_name = team.get('teamName', {}).get('name')

                    # Check for existing scorecard
                    unique_query = f"SELECT c.id FROM c WHERE c.EventId = '{data['EventId']}' AND c.judgeId = '{judge_id}' AND c.teamId = '{team_id}' AND c.category = '{category}'"
                    existing_entries = list(scorecard_container.query_items(query=unique_query, enable_cross_partition_query=True))

                    if existing_entries:
                        # Skip creating the entry if it already exists
                        continue

                    # Initialize scorecard with dynamic fields based on scorecardMeta
                    scorecard = {param['name']: 0 for param in get_category_entry(eventScoreCardMeta, category).get('parameters', [])}
                    scorecard['total'] = 0  # Initialize total score

                    # Create initial scorecard document
                    scorecard_document = {
                        'id': generate_unique_id(),
                        'EventId': data["EventId"],
                        'judgeId': judge_id,
                        'judgeName': judge_name,
                        'teamId': team_id,
                        'teamName': team_name,
                        'category': category,
                        'teamMemberId': None,  # Assuming we don't have specific team member ID here
                        'scorecard': scorecard,
                        'comments': '',
                        'CreationDateTimeStamp': datetime.now().isoformat()
                    }

                    # Insert scorecard document into container
                    try:
                        scorecard_container.create_item(body=scorecard_document)
                    except Exception as e:
                        return jsonify({"error": str(e)}), 500

        return jsonify({"status": "Scorecards created successfully"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/update_scores', methods=['POST'])
def update_scores():
    try:
        data = request.json
        scorecard_id=data["id"]
        eventId=data["EventId"]
        new_scores=data["scorecard"]
        comments=data["comment"]
        scorecard_container = database.get_container_client("EventScoreCard")
        # Retrieve the scorecard document from the database
        scorecard_document = scorecard_container.read_item(item=scorecard_id,partition_key=eventId)
        # Update the scores in the scorecard document
        scorecard_document['scorecard'].update(new_scores)
        scorecard_document['comments']=comments
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
        category=data.get('category')
        if not competition_id or not judge_id:
            return jsonify({"error": "Please provide both competitionId and judgeId in the request body"}), 400
        scorecard_container = database.get_container_client("EventScoreCard")
            # Query scorecards for the given competition_id and judge_id
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}' AND c.judgeId = '{judge_id}' AND c.teamId='{teamId}' AND c.category='{category}'"
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
        competition_id = data.get('EventId')

        # Initialize Cosmos DB container
        scorecard_container = database.get_container_client("EventScoreCard")
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
        scorecards = list(scorecard_container.query_items(query=query, enable_cross_partition_query=True))

        # Initialize dictionary to store scores per category
        category_scores = {}

        # Process each scorecard entry
        for scorecard in scorecards:
            team_id = scorecard.get('teamId')
            team_name = scorecard.get('teamName')
            category = scorecard.get('category')
            scorecard_data = scorecard.get('scorecard', {})

            # Compute score dynamically, excluding 'total'
            score_fields = [key for key in scorecard_data if key != 'total']
            score = sum(scorecard_data.get(field, 0) for field in score_fields)

            # Create a unique key for each team per category
            team_category_key = (team_name, category)

            if category not in category_scores:
                category_scores[category] = {}

            if team_category_key not in category_scores[category]:
                category_scores[category][team_category_key] = {
                    'teamId': team_id,
                    'teamName': team_name,
                    'category': category,
                    'total_score': 0
                }

            category_scores[category][team_category_key]['total_score'] += score

        # Prepare leaderboard sorted by categories and scores
        leaderboard = {}
        for category, scores in category_scores.items():
            sorted_scores = sorted(scores.values(), key=lambda x: x['total_score'], reverse=True)
            leaderboard[category] = sorted_scores

        return jsonify({"leaderboard": leaderboard}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


OUTLOOK_USER='nandhashriramsabbina@outlook.com'
OUTLOOK_PASSWORD='eakwnysdkybugfuh'  # Use App Password if 2-Step Verification is enabled
def read_html_content(file_path):
    with open(file_path, 'r') as file:
        return file.read()

@app.route('/send-email', methods=['POST'])
def send_email():
    data=request.json
    emails = data['emails']
    recipient = ', '.join(emails)
    recipient=recipient.split(",")
    subject = 'Test'
    html_content = read_html_content("emailInvite.html")
    formatted_html = format_html_content(html_content, entry)
    html_content.replace("PLACEHOLDER_COMPANY_NAME","Productions")
    html_content.replace("PLACEHOLDER_EVENT_TITLE","Productions")
    try:
        # Create the email message
        msg = MIMEMultipart()
        msg['From'] = GMAIL_USER
        msg['To'] = recipient
        msg['Subject'] = subject
        layout = read_html_content("scorecardLayout.html")
        emailContent={'mailContent':html_content}
        html_content = format_html_content(layout, emailContent)
        msg.attach(MIMEText(html_content, 'html'))
        # Connect to Gmail's SMTP server
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()  # Upgrade the connection to secure
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, recipient, msg.as_string())
    except Exception as e:
            print( jsonify({'error': str(e)}))
    return jsonify({'message': 'Email sent successfully with PDF attachment'})
def format_html_content(template, data):
    for key, value in data.items():
        placeholder = '{{' + key + '}}'
        template = template.replace(placeholder, str(value))
    return template



@app.route('/send-scorecard', methods=['POST'])
def sendScoreCardsemail():
    data=request.json
    pdf_filename="ScoreCard.pdf"
    competition_id=data['EventId']
    container = database.get_container_client("EventMeta")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    items = container.query_items(query=query, enable_cross_partition_query=True)
    metaData = list(items)
    metaData=metaData[0]
    container = database.get_container_client("EventTeamsJudges")
    query=f"SELECT *  FROM c WHERE c.EventId = '{competition_id}' "
    emailsData = list(container.query_items(query=query, enable_cross_partition_query=True))
    # Extract emails
    emails = []
    scorecard_container = database.get_container_client("EventScoreCard")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    scorecards = list(scorecard_container.query_items(query=query, enable_cross_partition_query=True))
    for entry in scorecards:
        subject="Score Card by "+entry['judgeName']+' for '+entry['category']
        entry['titleHeading']="Score Card For "+entry['category']
        entry['eventTitle']=metaData['eventTitle']
        for iteam in entry['scorecard']:
            entry[iteam]=entry['scorecard'][iteam]
        html_content = read_html_content("ScoreCard.html")
        formatted_html = format_html_content(html_content, entry)
        specific_team_id = entry['teamId']
        emails = []
        for event in emailsData:
            for team in event.get('teamsInfo', []):
                if team['teamName']['id'] == specific_team_id:
                    if team['teamRepresentativeEmail']['email']:
                        emails.append(team['teamRepresentativeEmail']['email'])
                    if team['coachName']['email']:
                        emails.append(team['coachName']['email'])
                    if team['DirectorName']['email']:
                        emails.append(team['DirectorName']['email'])
        createScoreCardPdf(entry['judgeName']+'_ScoreCard.pdf',entry)
        emails = list(filter(None, set(emails)))
        recipient = ', '.join(emails)
        recipient=recipient.split(",")
        for entry in recipient:
            try:
                # Create the email message
                msg = MIMEMultipart()
                msg['From'] = GMAIL_USER
                msg['To'] = entry
                msg['Subject'] = subject
                layout = read_html_content("scorecardLayout.html")
                emailContent={'mailContent':formatted_html}
                html_content = format_html_content(layout, emailContent)
                msg.attach(MIMEText(html_content, 'html'))

                with open(pdf_filename, 'rb') as pdf_file:
                    pdf_attachment = MIMEApplication(pdf_file.read(), _subtype='pdf')
                    pdf_attachment.add_header('Content-Disposition', 'attachment', filename=pdf_filename)
                    msg.attach(pdf_attachment)
                # Connect to Gmail's SMTP server
                with smtplib.SMTP('smtp.gmail.com', 587) as server:
                    server.starttls()  # Upgrade the connection to secure
                    server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                    server.sendmail(GMAIL_USER, recipient, msg.as_string())
            except Exception as e:
                return jsonify({'error': str(e)})
    return jsonify({'message': "success"})
def configureEventOrder(data):
    competition_id = data['EventId']
    scorecard_container = database.get_container_client("EventScoreCard")
    # Query scorecards for the given competition_id
    query = f"SELECT c.category, c.teamId, c.teamName FROM c WHERE c.EventId = @EventId"
    query_params = [{"name": "@EventId", "value": competition_id}]
    listPerformances = list(scorecard_container.query_items(
        query=query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))

    eventOrder_document = {
        "id": generate_unique_id(),
        "EventId": competition_id,
        "categoryOrder": []
    }

    seen = set()
    unique_listPerformances = []
    for performance in listPerformances:
        identifier = (performance['category'], performance['teamId'], performance['teamName'])
        if identifier not in seen:
            seen.add(identifier)
            unique_listPerformances.append(performance)

    # Organize performances by category
    categories = {}
    for performance in unique_listPerformances:
        category = performance.get("category")
        team_id = performance.get("teamId")
        team_name = performance.get("teamName")

        if category not in categories:
            categories[category] = []

        categories[category].append({
            "teamId": team_id,
            "teamName": team_name,
        })

    for category_index, (category, teams) in enumerate(categories.items(), start=1):
        eventOrder_document["categoryOrder"].append({
            "category": category,
            "order": category_index,
            "performances": []
        })

        for team_index, team in enumerate(teams, start=1):
            team_with_order = team.copy()
            team_with_order["order"] = team_index
            eventOrder_document["categoryOrder"][-1]["performances"].append(team_with_order)

    # Container for EventOrderConfig
    Ordercontainer = database.get_container_client("EventOrderConfig")
    
    try:
        # Check if the event order document already exists
        existing_documents = list(Ordercontainer.query_items(
            query="SELECT * FROM c WHERE c.EventId = @EventId",
            parameters=query_params,
            enable_cross_partition_query=True
        ))

        if existing_documents:
            # If exists, replace the document
            existing_document = existing_documents[0]
            updated_document = Ordercontainer.replace_item(item=existing_document['id'], body=eventOrder_document)
            return jsonify(updated_document), 200
        else:
            # If does not exist, create a new document
            eventOrder_document["CreationDateTimeStamp"]=datetime.now().isoformat()
            new_document = Ordercontainer.create_item(body=eventOrder_document)
            return jsonify(new_document), 201

    except exceptions.CosmosResourceNotFoundError:
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
def configureEventOrderMain(data):
    competition_id = data['EventId']
    container = database.get_container_client("EventTeamsJudges")
    meta_conatiner = database.get_container_client("EventMeta")
    # Query scorecards for the given competition_id
    query = f"SELECT c.teamsInfo FROM c WHERE c.EventId = @EventId"
    category_query=f"SELECT c.eventCategory FROM c WHERE c.EventId = @EventId"
    query_params = [{"name": "@EventId", "value": competition_id}]
    listCategory = list(meta_conatiner.query_items(
        query=category_query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))
    listPerformances = list(container.query_items(
        query=query,
        parameters=query_params,
        enable_cross_partition_query=True
    ))

    eventOrder_document = {
        "id": generate_unique_id(),
        "EventId": competition_id,
        "categoryOrder": []
    }

    seen = set()
    unique_listPerformances = []
    for category in listCategory[0]['eventCategory']:
        for performance in listPerformances[0]['teamsInfo']:
            identifier = (category, performance['teamName']['id'], performance['teamName']['name'])
            data = {
            'category': category,
            'teamId': performance['teamName']['id'],
            'teamName': performance['teamName']['name']
            }
            if identifier not in seen:
                seen.add(identifier)
                unique_listPerformances.append(data)

    # Organize performances by category
    categories = {}
    for performance in unique_listPerformances:
        category = performance.get("category")
        team_id = performance.get("teamId")
        team_name = performance.get("teamName")

        if category not in categories:
            categories[category] = []

        categories[category].append({
            "teamId": team_id,
            "teamName": team_name,
        })

    for category_index, (category, teams) in enumerate(categories.items(), start=1):
        eventOrder_document["categoryOrder"].append({
            "category": category,
            "order": category_index,
            "performances": []
        })

        for team_index, team in enumerate(teams, start=1):
            team_with_order = team.copy()
            team_with_order["order"] = team_index
            eventOrder_document["categoryOrder"][-1]["performances"].append(team_with_order)

    # Container for EventOrderConfig
    Ordercontainer = database.get_container_client("EventOrderConfig")
    
    try:
        # Check if the event order document already exists
        existing_documents = list(Ordercontainer.query_items(
            query="SELECT * FROM c WHERE c.EventId = @EventId",
            parameters=query_params,
            enable_cross_partition_query=True
        ))

        if existing_documents:
            # If exists, replace the document
            existing_document = existing_documents[0]
            updated_document = Ordercontainer.replace_item(item=existing_document['id'], body=eventOrder_document)
            return jsonify(updated_document), 200
        else:
            # If does not exist, create a new document
            eventOrder_document["CreationDateTimeStamp"]=datetime.now().isoformat()
            new_document = Ordercontainer.create_item(body=eventOrder_document)
            return jsonify(new_document), 201

    except exceptions.CosmosResourceNotFoundError:
        return jsonify({"error": "Resource not found"}), 404
    except exceptions.CosmosHttpResponseError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500        
@app.route('/getEventOrder', methods=['POST'])
def getEventOrder():
    Ordercontainer = database.get_container_client("EventOrderConfig")
    data=request.json
    competition_id=data['EventId']
    try:
        query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
        eventOrder_document = list(Ordercontainer.query_items(query=query, enable_cross_partition_query=True))
        return  eventOrder_document[0], 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route('/updateEventOrder', methods=['POST'])
def updateEventOrder():
    Ordercontainer = database.get_container_client("EventOrderConfig")
    data=request.json
    competition_id=data['EventId']
    order_id=data['id']
    try:
        updated_document = Ordercontainer.replace_item(item=order_id, body=data)
        return  updated_document, 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
def createScoreCardPdf(filename,data):
    try:
        doc = SimpleDocTemplate(filename, pagesize=letter)
        styles = getSampleStyleSheet()
        elements = []

        # Title
        title_style = styles['Title']
        title_style.fontName = 'Helvetica-Bold'
        title_style.fontSize = 24
        title_style.alignment = TA_CENTER
        title = Paragraph("Score Card", title_style)
        elements.append(title)
        elements.append(Spacer(1, 0.5 * inch))

        for entry in data:
            # Event Title
            event_title_style = styles['Heading1']
            event_title_style.fontName = 'Helvetica-Bold'
            event_title_style.fontSize = 20
            event_title_style.alignment = TA_CENTER
            event_title = Paragraph(f"{entry['eventTitle']}", event_title_style)
            elements.append(event_title)
            elements.append(Spacer(1, 0.25 * inch))

            # Judge and Team Details
            details_style = styles['Normal']
            details_style.fontName = 'Helvetica'
            details_style.fontSize = 12
            details_style.alignment = TA_LEFT
            judge_name = Paragraph(f"<b>Judge:</b> {entry['judgeName']}", details_style)
            team_name = Paragraph(f"<b>Team:</b> {entry['teamName']}", details_style)
            comments = Paragraph(f"<b>Comments:</b> {entry['Comments']}", details_style)
            elements.append(judge_name)
            elements.append(team_name)
            elements.append(comments)
            elements.append(Spacer(1, 0.5 * inch))

            # Performance Table
            table_data = [
                ["Category", "Score"],
                ["Creativity", entry['creativity']],
                ["Difficulty", entry['difficulty']],
                ["Formation", entry['formation']],
                ["Sync", entry['sync']],
                ["Technique", entry['technique']],
                ["Total", entry['total']]
            ]

            table = Table(table_data, colWidths=[2.5 * inch, 1.5 * inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4CAF50')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 0.5 * inch))

        # Build PDF
        doc.build(elements)
    except Exception as e:
         print(jsonify({"error": str(e)}), 500)


def create_pdf(filename, data,eventOrder):
    doc = SimpleDocTemplate(filename, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    title = Paragraph("Event Schedule", styles['Title'])
    elements.append(title)
    elements.append(Paragraph("<br/>", styles['Normal']))

    # Event Title
    event_id = Paragraph(f"{data.get('eventTitle', '')}", styles['Normal'])
    elements.append(event_id)
    elements.append(Paragraph("<br/>", styles['Normal']))
    # Event Venue String
    event_id = Paragraph(f"Venue :{data.get('eventVenue', '')}", styles['Normal'])
    elements.append(event_id)
    elements.append(Paragraph("<br/>", styles['Normal']))
    # Event Data String
    event_id = Paragraph(f"Date and Time :{data.get('eventDateString', '')}", styles['Normal'])
    elements.append(event_id)
    elements.append(Paragraph("<br/>", styles['Normal']))

    # Categories and Performances
    for category in eventOrder['categoryOrder']:
        category_title = Paragraph(f"<b>Category: {category['category']} (Order: {category['order']})</b>", styles['Heading2'])
        elements.append(category_title)
        # Table Data
        table_data = [["Order", "Team Name"]]  # Removed "Team ID"
        for performance in category['performances']:
            table_data.append([performance['order'], performance['teamName']])  # Removed "Team ID"
        # Create Table
        table = Table(table_data, colWidths=[1 * inch, 2.5 * inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 1, black),
        ]))
        elements.append(table)
        elements.append(Paragraph("<br/>", styles['Normal']))

    # Build PDF
    doc.build(elements)

# Route to send email with PDF attachment
@app.route('/sendEventSchedule', methods=['POST'])
def send_email_with_pdf():
    data = request.json
    competition_id = data.get('EventId')
    # Initialize Cosmos Client
    container = database.get_container_client("EventMeta")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    items = container.query_items(query=query, enable_cross_partition_query=True)
    eventCategorys = list(items)
    data=eventCategorys[0]
    query=f"SELECT *  FROM c WHERE c.EventId = '{competition_id}' "
    subject = (data.get('eventTitle', '') + '|' +
           data.get('eventDateString', '') + '|' +
           data.get('eventVenue', '') + ' Schedule')    # Create the PDF
    Ordercontainer = database.get_container_client("EventOrderConfig")
    competition_id=data['EventId']
    container = database.get_container_client("EventTeamsJudges")
    emailsData = list(container.query_items(query=query, enable_cross_partition_query=True))
    # Extract emails
    emails = []

# Extract team representative, coach, and director emails
    for event in emailsData:
        for team in event.get('teamsInfo', []):
            if team['teamRepresentativeEmail']['email']:
                emails.append(team['teamRepresentativeEmail']['email'])
            if team['coachName']['email']:
                emails.append(team['coachName']['email'])
            if team['DirectorName']['email']:
                emails.append(team['DirectorName']['email'])
    # Remove empty strings (if any) and duplicates
    emails = list(filter(None, set(emails)))
    recipient = ','.join(emails)
    recipient=recipient.split(",")
    query = f"SELECT * FROM c WHERE c.EventId = '{competition_id}'"
    eventOrder_document = list(Ordercontainer.query_items(query=query, enable_cross_partition_query=True))
    #create_pdf(pdf_filename, data,eventOrder_document[0])
    # Read and format HTML content
    firsthtml = read_html_content("EventSchedule-converted.html")
    firsthtml=format_html_content(firsthtml, data)
    for category in eventOrder_document[0]['categoryOrder']:
        html_content = read_html_content("categoryEventTag.html")
        tagData={}
        tagData['Category']=category['category']
        # Table Data
        table_data = [["Order", "Team Name"]]  # Removed "Team ID"
        orderTags=''
        for performance in category['performances']:
            perData={}
            entryTag = read_html_content("orderandTeamTag.html")
            perData['order']=performance['order']
            perData['TeamName']=performance['teamName']
            orderTags=orderTags+format_html_content(entryTag, perData)
        tagData['orderTags']  = orderTags
        firsthtml = firsthtml+format_html_content(html_content, tagData)
    firsthtml=firsthtml+read_html_content("EventScheduleEnd.html")
    for entry in recipient:
        try:
            # Create the email message
            msg = MIMEMultipart()
            msg['From'] = GMAIL_USER
            msg['To'] = entry
            msg['Subject'] = subject
            layout = read_html_content("scorecardLayout.html")
            emailContent={'mailContent':firsthtml}
            html_content = format_html_content(layout, emailContent)
            msg.attach(MIMEText(html_content, 'html'))


            # Connect to Gmail's SMTP server
            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.starttls()  # Upgrade the connection to secure
                server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                server.sendmail(GMAIL_USER, recipient, msg.as_string())
            # Clean up
        except Exception as e:
            print( jsonify({'error': str(e)}))
    return jsonify({'message': 'Email sent successfully with PDF attachment'})
        
if __name__ == "__main__":
    app.run(host="0.0.0.0",port=5001)


