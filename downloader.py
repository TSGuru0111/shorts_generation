import os
import re
import json
import pickle
import subprocess
import requests
from pytube import YouTube
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from urllib.parse import parse_qs, urlparse
import io
import requests

class VideoDownloadError(Exception):
    pass

def get_youtube_service():
    """Get authenticated YouTube API service"""
    creds = None
    token_path = 'token.pickle'
    secrets_path = 'client_secrets.json'
    
    # Check if we have valid credentials
    if os.path.exists(token_path):
        with open(token_path, 'rb') as token:
            creds = pickle.load(token)
    
    # If no valid credentials, get new ones
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(secrets_path):
                print(f"Please create {secrets_path} using the template and add your credentials")
                return None
                
            flow = InstalledAppFlow.from_client_secrets_file(
                secrets_path,
                ['https://www.googleapis.com/auth/youtube.force-ssl']
            )
            creds = flow.run_local_server(port=8080)
            
        # Save credentials
        with open(token_path, 'wb') as token:
            pickle.dump(creds, token)
    
    return build('youtube', 'v3', credentials=creds)

def get_video_info(service, video_id):
    """Get video information using YouTube API"""
    try:
        request = service.videos().list(
            part="snippet,contentDetails",
            id=video_id
        )
        response = request.execute()
        
        if response['items']:
            return response['items'][0]
        return None
    except Exception as e:
        print(f"Error getting video info: {str(e)}")
        return None

def download_with_api(url, output_path):
    """Download video using YouTube API"""
    try:
        # Extract video ID from URL
        query = parse_qs(urlparse(url).query)
        video_id = query.get('v', [None])[0]
        if not video_id:
            print("Could not extract video ID from URL")
            return None
            
        # Get YouTube service
        service = get_youtube_service()
        if not service:
            print("Could not initialize YouTube service")
            return None
            
        # Get video info
        video_info = get_video_info(service, video_id)
        if not video_info:
            print("Could not get video information")
            return None
            
        print(f"Found video: {video_info['snippet']['title']}")
        
        # Download video using PyTube as it's more reliable for actual downloading
        try:
            yt = YouTube(url)
            stream = yt.streams.filter(
                progressive=True,
                file_extension='mp4',
                resolution='720p'
            ).first()
            
            if not stream:
                stream = yt.streams.filter(
                    progressive=True,
                    file_extension='mp4'
                ).order_by('resolution').desc().first()
            
            if stream:
                print(f"Downloading {stream.resolution} stream...")
                stream.download(filename=output_path)
                if os.path.exists(output_path):
                    print(f"Download successful: {output_path}")
                    return output_path
        except Exception as e:
            print(f"PyTube download failed: {str(e)}")
        
        print("API download failed")
        return None
        
    except Exception as e:
        print(f"API error: {str(e)}")
        if os.path.exists(output_path):
            os.remove(output_path)
        return None

def download_with_pytube(url, output_path):
    """Download video using PyTube with better error handling"""
    try:
        print("Initializing PyTube...")
        yt = YouTube(url)
        
        print("Finding best stream...")
        # Try to get a stream with both video and audio
        stream = yt.streams.filter(
            progressive=True,  # Contains both video and audio
            file_extension='mp4',
            resolution='720p'
        ).first()
        
        # If no 720p stream, try any resolution
        if not stream:
            print("No 720p stream found, trying other resolutions...")
            stream = yt.streams.filter(
                progressive=True,
                file_extension='mp4'
            ).order_by('resolution').desc().first()
        
        if stream:
            print(f"Downloading stream: {stream.resolution}")
            stream.download(filename=output_path)
            if os.path.exists(output_path):
                print(f"PyTube download successful: {output_path}")
                return output_path
    except Exception as e:
        print(f"PyTube download failed: {str(e)}")
        if os.path.exists(output_path):
            os.remove(output_path)
    return None

def download_with_invidious(url, output_path, invidious_instance="https://invidious.snopyta.org"):
    """Download video using Invidious API"""
    try:
        # Extract video ID
        video_id = url.split('v=')[-1]
        if '&' in video_id:
            video_id = video_id.split('&')[0]
            
        print(f"Fetching video info from Invidious...")
        api_url = f"{invidious_instance}/api/v1/videos/{video_id}"
        
        # Try multiple Invidious instances
        instances = [
            "https://invidious.snopyta.org",
            "https://yewtu.be",
            "https://invidious.kavin.rocks",
            "https://vid.puffyan.us"
        ]
        
        for instance in instances:
            try:
                print(f"Trying Invidious instance: {instance}")
                api_url = f"{instance}/api/v1/videos/{video_id}"
                resp = requests.get(api_url, timeout=10)
                if resp.ok:
                    info = resp.json()
                    
                    # Get best quality video stream (720p or lower)
                    streams = [s for s in info['videoStreams'] 
                              if s['quality'].lower().replace('p', '').isdigit() 
                              and int(s['quality'].lower().replace('p', '')) <= 720]
                    
                    if not streams:
                        print(f"No suitable streams found from {instance}")
                        continue
                        
                    # Sort by quality (highest first)
                    streams.sort(key=lambda x: int(x['quality'].lower().replace('p', '')), reverse=True)
                    video_url = streams[0]['url']
                    
                    print(f"Downloading {streams[0]['quality']} video...")
                    r = requests.get(video_url, stream=True, timeout=30)
                    r.raise_for_status()
                    
                    total_size = int(r.headers.get('content-length', 0))
                    block_size = 8192
                    wrote = 0
                    
                    with open(output_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=block_size):
                            if chunk:
                                wrote = wrote + len(chunk)
                                f.write(chunk)
                                if total_size > 0:
                                    done = int(50 * wrote / total_size)
                                    print(f"\rDownloading: [{'=' * done}{' ' * (50-done)}] {wrote}/{total_size} bytes", end='')
                    
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                        print(f"\nDownload complete: {output_path}")
                        return output_path
                        
            except Exception as e:
                print(f"Error with {instance}: {str(e)}")
                continue
                
        print("All Invidious instances failed")
        return None
        
    except Exception as e:
        print(f"Invidious download failed: {str(e)}")
        if os.path.exists(output_path):
            os.remove(output_path)
        return None

def download_with_ytdlp(url, output_path, cookies_path=None):
    """Download video using yt-dlp with working options"""
    try:
        # Remove existing file if it exists
        if os.path.exists(output_path):
            print(f"Removing existing file: {output_path}")
            os.remove(output_path)

        print(f"Attempting yt-dlp download from {url}")

        # Base command with working options
        cmd = [
            'yt-dlp',
            '--format', 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best',
            '--merge-output-format', 'mp4',
            '--output', output_path,
            '--no-playlist',
            '--no-warnings',
            '--ignore-config',
            '--geo-bypass',
            '--force-ipv4',
            '--no-part',
            '--retries', '10',
            '--fragment-retries', '10',
            url
        ]

        print("Downloading video...")
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        # Check if download succeeded
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print(f"\nyt-dlp download successful: {output_path}")
            return output_path

        # If failed and it's age-restricted, try with cookies
        if 'age-restricted' in (result.stderr or '').lower():
            print("\nVideo is age-restricted, retrying with cookies...")
            cmd.extend(['--cookies-from-browser', 'chrome'])
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)

            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                print(f"\nyt-dlp download successful with cookies: {output_path}")
                return output_path

        # If still failed, try with best format
        print("\nRetrying with best format...")
        cmd = [
            'yt-dlp',
            '--format', 'best',
            '--output', output_path,
            '--no-playlist',
            '--no-warnings',
            '--ignore-config',
            '--geo-bypass',
            url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print(f"\nyt-dlp download successful with best format: {output_path}")
            return output_path

        print(f"\nyt-dlp download failed: {result.stderr if result.stderr else 'Unknown error'}")
        return None

    except Exception as e:
        print(f"yt-dlp error: {str(e)}")
        if os.path.exists(output_path):
            os.remove(output_path)
        return None

def fallback_sample(output_path):
    # Copy or generate a sample video if all else fails
    sample = os.path.join(os.path.dirname(__file__), 'sample.mp4')
    if os.path.exists(sample):
        import shutil
        shutil.copy(sample, output_path)
        return output_path
    return None

def download_with_direct(url, output_path):
    """Try to download video directly using requests"""
    try:
        # First get video info using a simple request
        print("Trying direct download...")
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # Try to get the video page
        response = session.get(url)
        if not response.ok:
            print(f"Failed to get video page: {response.status_code}")
            return None
            
        # Look for video URL in the page content
        content = response.text
        video_urls = re.findall(r'"url":"(https://[^"]*\.mp4[^"]*)', content)
        if not video_urls:
            print("No direct video URLs found")
            return None
            
        # Try each URL
        for video_url in video_urls:
            try:
                print(f"Trying URL: {video_url}")
                
                # Download the video
                response = session.get(video_url, stream=True)
                if response.ok:
                    total_size = int(response.headers.get('content-length', 0))
                    block_size = 8192
                    wrote = 0
                    
                    with open(output_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=block_size):
                            if chunk:
                                wrote = wrote + len(chunk)
                                f.write(chunk)
                                if total_size > 0:
                                    done = int(50 * wrote / total_size)
                                    print(f"\rDownloading: [{'=' * done}{' ' * (50-done)}] {wrote}/{total_size} bytes", end='')
                                    
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                        print(f"\nDirect download successful: {output_path}")
                        return output_path
            except Exception as e:
                print(f"Error with URL {video_url}: {str(e)}")
                continue
                
        print("No working direct download URLs found")
        return None
        
    except Exception as e:
        print(f"Direct download failed: {str(e)}")
        if os.path.exists(output_path):
            os.remove(output_path)
        return None

def download_video(url: str, output_path: str = "input.mp4") -> str:
    """Download video using yt-dlp with fallbacks"""
    try:
        # Remove existing file if it exists
        if os.path.exists(output_path):
            print(f"Removing existing file: {output_path}")
            os.remove(output_path)

        print(f"\nDownloading video from {url}...")
        
        # Try yt-dlp first
        result = download_with_ytdlp(url, output_path)
        if result:
            return result
            
        # Try PyTube next
        print("\nTrying PyTube...")
        result = download_with_pytube(url, output_path)
        if result:
            return result
        
        # Try Invidious as last resort
        print("\nTrying Invidious...")
        result = download_with_invidious(url, output_path)
        if result:
            return result
            
        print("All download methods failed")
        return None
        
    except Exception as e:
        print(f"Error downloading video: {str(e)}")
        if os.path.exists(output_path):
            os.remove(output_path)
        return None

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python downloader.py <youtube_url> [output_path]")
        sys.exit(1)
    
    url = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "input.mp4"
    
    result = download_video(url, output_path)
    
    if result:
        print(f"Video successfully downloaded to {result}")
    else:
        print("Failed to download video")
        sys.exit(1)
