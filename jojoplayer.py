#!/usr/bin/env python3
# Importing all the tools which we need to do different tasks
from email import header
import requests  # Helps us talk to websites
import re  # Helps us find patterns in text
import csv  # Helps us read and write CSV files
import time  # Helps us work with time
from bs4 import BeautifulSoup  # Helps us read web pages
from csv import writer  # Helps us write CSV files
from urllib.request import Request, urlopen  # Helps us open web pages
import requests, random  # Helps us talk to websites and pick random things
import urllib.request  # Helps us open web pages
import re  # Helps us find patterns in text
import os  # Helps us work with files and folders
import shutil  # Helps us move files around
import pymysql  # Using PyMySQL instead of mysql.connector
import paramiko  # Helps us connect to other computers
import os  # Helps us work with files and folders
import ftplib  # Helps us transfer files
import sys  # Helps us interact with the system
import subprocess  # Helps us run other programs
import time  # Helps us work with time
import asyncio  # Helps us do many things at once

import json  # Helps us work with JSON data
from datetime import datetime, timedelta, timezone  # Helps us work with dates and times
import ftplib  # Helps us transfer files
import requests  # Helps us talk to websites
from requests.packages.urllib3.exceptions import InsecureRequestWarning  # Helps us handle warnings
from pushover_notify import PushoverNotifier  # Helps us send push notifications
import os  # Helps us work with environment variables
from urllib.parse import urlparse  # Helps us parse database URLs

# We don't want to see warnings about insecure requests
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Parse DATABASE_URL from environment
db_url = os.getenv('DATABASE_URL')
parsed = urlparse(db_url)
DB_HOST = parsed.hostname
DB_PORT = parsed.port or 3306
DB_USER = parsed.username
DB_PASSWORD = parsed.password
DB_NAME = parsed.path.lstrip('/')

# A list of pretend browsers we can use to visit websites
user_agent_list = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.131 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.169 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:66.0) Gecko/20100101 Firefox/66.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.157 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KTML, like Gecko) Chrome/73.0.3683.103 Safari/537.36',
    'Mozilla/5.0 (Windows NT 6.1; WOW64; Trident/7.0; AS; rv:11.0) like Gecko',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; Trident/7.0; AS; rv:11.0) like Gecko',
    'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:60.0) Gecko/20100101 Firefox/60.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/76.0.3809.132 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/12.1.2 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64; rv:68.0) Gecko/20100101 Firefox/68.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/76.0.3809.132 Safari/537.36',
    'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:68.0) Gecko/20100101 Firefox/68.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/77.0.3865.90 Safari/537.36',
    'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:72.0) Gecko/20100101 Firefox/72.0',
]
# Pick a random pretend browser from the list
user_agent = random.choice(user_agent_list)

# Set up headers to use the pretend browser
headers = {'User-Agent': user_agent}

# Initialize pushover notifier for error notifications
notifier = PushoverNotifier()

try:
    # Try to connect to the database using PyMySQL
    db = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset='utf8mb4',
        connect_timeout=30
    )
    
    # Check if we are connected to the database
    print("Connected to the MySQL database.")
except Exception as e:
    # If there was an error, print it and stop the program
    print(f"Database connection error: {str(e)}")
    notifier.send_exception("add_links_viralweb8.py", e)
    sys.exit(1)

# We want to keep checking for new videos
loop = True
# Assume all videos are processed
all_processed = True
# This will hold updated video links
updated_data = None

# Keep checking for new videos until we say stop
while loop:
    try:
        # Get ready to look at the movie data
        movies_cursor = db.cursor(pymysql.cursors.DictCursor)
        # Find movies that haven't been processed yet
        sql = "SELECT id, title, pixeldrain, viralweb8, link, year_name FROM movie_data WHERE viralweb8 = '0' ORDER BY id DESC LIMIT 10"
        movies_cursor.execute(sql)
        viralweb8_rows = movies_cursor.fetchall()
        
        # Go through each movie we found
        for viralweb8_row in viralweb8_rows:
            try:
                if 'pixeldrain' in viralweb8_row and viralweb8_row['pixeldrain'] and viralweb8_row['pixeldrain'].strip():
                    # Process this movie using R2 CDN link
                    video_link = f"http://cdn.jojoplayer.com/{viralweb8_row['pixeldrain'].strip()}"
                    print(video_link)
                    
                    # Set priority based on year - priority 1 for 2025, no priority for others
                    year_name = viralweb8_row.get('year_name')
                    if year_name == '2026':
                        print(f"Processing {viralweb8_row['title']} (Year: {year_name}, Priority: 1)")
                        url = f"https://embedojo.net/api/addVideo.php?key=psFx3j6O3&url={video_link}&priority=1&member=254&server=rand&disk=rand"
                    else:
                        print(f"Processing {viralweb8_row['title']} (Year: {year_name}, Priority: none)")
                        url = f"https://embedojo.net/api/addVideo.php?key=psFx3j6O3&url={video_link}&member=254&server=rand&disk=rand"
            
                    # Ask the website to add the video
                    response = requests.get(url, headers=headers, verify=False)
                    viralweb8 = json.loads(response.text)
                    print(viralweb8)

                    # If the video was added successfully
                    if viralweb8['status'] == 'success':
                        # Get the new link for the video
                        url = 'https://embedojo.net/api/getVideo.php?key=psFx3j6O3&id=' + viralweb8['id']
                        response = requests.get(url, headers=headers, verify=False)
                        viralweb8 = json.loads(response.text)
                        new_link = viralweb8['data']['url-list']['url']
                        
                        # If we got a new link
                        if new_link != 'None':
                            # Check if there is already a link in the database
                            cursor = db.cursor()
                            cursor.execute("SELECT link FROM movie_data WHERE id = '" + str(viralweb8_row['id']) + "'")
                            existing_data = cursor.fetchone()[0]

                            # If there is, add the new link to it
                            if existing_data is not None:
                                updated_data = f"{existing_data}, {new_link}"
                            else:
                                # If not, just use the new link
                                updated_data = f"{new_link}"

                            # Make sure there are no empty links
                            updated_data_array = updated_data.split(',')
                            updated_data = [item.strip() for item in updated_data_array if item.strip()]
                            updated_data = ','.join(updated_data)

                            # Get the current date and time
                            current_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                            try:
                                # Update the database with the new link and time
                                cursor.execute(f"UPDATE movie_data SET link = '{updated_data}', video_uploaded_time = '{current_datetime}', viralweb8 = '1' WHERE id = '" + str(viralweb8_row['id']) + "'")
                                db.commit()
                            except Exception as err:
                                # If there is an error, print it
                                print("Error: ", err)
                                notifier.send_exception("add_links_viralweb8.py", err)
                            finally:
                                # Close the cursor
                                cursor.close()
                else:
                    # Skip this record if no filename is available
                    print(f"Skipping {viralweb8_row['title']}: No filename found in pixeldrain column")
                    continue
            except Exception as e:
                # If there is an error with a video, print it and keep going
                print(f"Error processing video {viralweb8_row['title']}: {str(e)}")
                continue

        # If we updated any data, print it
        if updated_data:
            print(updated_data)
        elif all_processed:
            # If all videos are processed, say so
            print("All videos are processed")
        else:
            # If some videos were not processed, say so
            print("Some videos were not processed")

        # Stop the loop
        loop = False

    except Exception as e:
        # If there is an error in the main loop, print it and stop
        print(f"Main loop error: {str(e)}")
        notifier.send_exception("add_links_viralweb8.py", e)
        break

# Close the connection to the database
db.close()
print("Disconnected from the MySQL database.")
# Stop the program
sys.exit() 
