import argparse
import os
from downloader import download_video
from transcriber import WhisperTranscriber, TranscriptionResult
from scene_detector import SceneDetector, Scene
from highlight_selector import HighlightSelector
from dotenv import load_dotenv
import subprocess
import os
import tempfile
import shutil
from pathlib import Path
import re
import textwrap

def generate_title_from_text(text):
    """Generate a catchy title from the text"""
    # Clean the text - remove all special characters
    text = re.sub(r'[^\w\s]', '', text)
    words = text.split()
    
    # If text is short enough, use it directly
    if len(text) < 30:
        return text.upper()
    
    # Otherwise, extract key phrases or use first few words
    if len(words) > 5:
        title = ' '.join(words[:5]) + '...'
    else:
        title = text
    
    # Ensure the title is safe for ffmpeg
    return title.upper().replace("'", "").replace("\"", "")

def generate_captions(highlight, transcription_result):
    """Generate captions for the video with proper timing"""
    captions = []
    start_time = highlight.start_time
    
    # Get words in the highlight timerange
    words = transcription_result.get_words_in_timerange(highlight.start_time, highlight.end_time)
    
    if not words:
        return captions
    
    # Group words into caption lines (max 40 chars per line)
    current_line = ""
    line_start_time = words[0]['start']
    
    for word in words:
        if len(current_line + " " + word['text']) > 40:
            # Add current line to captions
            captions.append({
                'start_time': line_start_time - highlight.start_time,
                'end_time': word['start'] - highlight.start_time,
                'text': current_line.strip()
            })
            # Start new line
            current_line = word['text']
            line_start_time = word['start']
        else:
            # Add word to current line
            if current_line:
                current_line += " " + word['text']
            else:
                current_line = word['text']
    
    # Add the last line if not empty
    if current_line:
        captions.append({
            'start_time': line_start_time - highlight.start_time,
            'end_time': words[-1]['end'] - highlight.start_time,
            'text': current_line.strip()
        })
    
    return captions

def create_subtitle_file(file_path, captions):
    """Create an SRT subtitle file from captions"""
    with open(file_path, 'w', encoding='utf-8') as f:
        for i, caption in enumerate(captions, 1):
            # Convert times to SRT format (HH:MM:SS,mmm)
            start_time_str = format_srt_time(caption['start_time'])
            end_time_str = format_srt_time(caption['end_time'])
            
            # Write subtitle entry
            f.write(f"{i}\n")
            f.write(f"{start_time_str} --> {end_time_str}\n")
            f.write(f"{caption['text']}\n\n")

def format_srt_time(seconds):
    """Format seconds to SRT time format (HH:MM:SS,mmm)"""
    hours = int(seconds / 3600)
    minutes = int((seconds % 3600) / 60)
    seconds = seconds % 60
    milliseconds = int((seconds - int(seconds)) * 1000)
    
    return f"{hours:02d}:{minutes:02d}:{int(seconds):02d},{milliseconds:03d}"

def main():
    # Load environment variables
    load_dotenv()
    
    parser = argparse.ArgumentParser(description="YouTube Shorts Generator")
    parser.add_argument('--youtube-url', type=str, required=True, help='YouTube video URL')
    parser.add_argument('--output', type=str, default='input.mp4', help='Downloaded video output path')
    parser.add_argument('--cookies', type=str, default='cookies.txt', help='Path to browser cookies for yt-dlp')
    parser.add_argument('--whisper-model', type=str, default='base', help='Whisper model size (tiny, base, small, medium, large)')
    parser.add_argument('--language', type=str, help='Language code for transcription (e.g., en, es)')
    parser.add_argument('--min-scene-len', type=float, default=0.5, help='Minimum scene length in seconds')
    parser.add_argument('--scene-threshold', type=int, default=27, help='Threshold for content change detection (0-255)')
    parser.add_argument('--min-highlight-duration', type=float, default=30.0, help='Minimum highlight duration in seconds')
    parser.add_argument('--max-highlight-duration', type=float, default=90.0, help='Maximum highlight duration in seconds')
    parser.add_argument('--max-highlights', type=int, default=5, help='Maximum number of highlights to generate')
    parser.add_argument('--shorts-output', type=str, default='shorts', help='Output directory for shorts videos')
    parser.add_argument('--aspect-ratio', type=str, default='9:16', help='Aspect ratio for shorts videos (e.g., 9:16 for vertical)')
    args = parser.parse_args()

    print("[1/7] Downloading video...")
    video_path = download_video(args.youtube_url, args.output)
    if not video_path:
        print("Download failed")
        return

    print("[2/7] Transcribing video...")
    try:
        transcriber = WhisperTranscriber(model_size=args.whisper_model)
        result = transcriber.transcribe(video_path, language=args.language)
        print(f"Transcribed {len(result.words)} words")
        
        # Get potential speech-based segments
        segments = transcriber.get_speech_segments(result)
        print(f"Identified {len(segments)} potential segments")
        
    except Exception as e:
        print(f"Transcription failed: {e}")
        return
    
    print("[3/7] Detecting scenes...")
    try:
        detector = SceneDetector(min_scene_len=args.min_scene_len, threshold=args.scene_threshold)
        scenes = detector.detect_scenes(video_path, segments)
        
        # Merge very short scenes
        scenes = detector.merge_short_scenes(scenes, min_duration=1.0)
        
        print(f"Detected {len(scenes)} scenes after merging")
        
        # Print some scene statistics
        total_duration = sum(scene.duration for scene in scenes)
        avg_duration = total_duration / len(scenes) if scenes else 0
        print(f"Average scene duration: {avg_duration:.2f} seconds")
        
        speech_scenes = [s for s in scenes if s.speech_segments]
        print(f"Scenes with speech: {len(speech_scenes)} ({(len(speech_scenes)/len(scenes)*100):.1f}%)")
        
    except Exception as e:
        print(f"Scene detection failed: {e}")
        return
    
    print("[4/7] Selecting highlights...")
    try:
        # Initialize highlight selector with optional Cohere API key
        cohere_api_key = os.getenv('COHERE_API_KEY')
        selector = HighlightSelector(
            cohere_api_key=cohere_api_key,
            min_duration=args.min_highlight_duration,
            max_duration=args.max_highlight_duration
        )
        
        # Select best highlights
        highlights = selector.select_highlights(
            scenes=scenes,
            transcription_result=result,
            max_highlights=args.max_highlights
        )
        
        print(f"\nSelected {len(highlights)} highlights:")
        for i, highlight in enumerate(highlights, 1):
            duration = highlight.end_time - highlight.start_time
            print(f"\nHighlight {i}/{len(highlights)}:")
            print(f"Time: {highlight.start_time:.1f}s - {highlight.end_time:.1f}s ({duration:.1f}s)")
            print(f"Score: {highlight.score:.2f}")
            print(f"Text: {highlight.text[:100]}..." if len(highlight.text) > 100 else f"Text: {highlight.text}")
        
    except Exception as e:
        print(f"Highlight selection failed: {e}")
        return
    
    # [5/7] Generating highlight clips with ffmpeg in vertical format
    print("[5/7] Generating highlight clips in vertical format...")
    
    # Create output directory if it doesn't exist
    output_dir = args.shorts_output
    os.makedirs(output_dir, exist_ok=True)
    
    # Create temporary directory for processing
    temp_dir = tempfile.mkdtemp()
    
    # Parse aspect ratio
    aspect_ratio = args.aspect_ratio.split(':')
    target_width = 1080  # Standard width for vertical videos
    target_height = int(target_width * int(aspect_ratio[1]) / int(aspect_ratio[0]))
    
    print(f"Creating videos with resolution {target_width}x{target_height}")
    
    # Process each highlight as a separate short video
    for i, hl in enumerate(highlights):
        print(f"\nProcessing highlight {i+1}/{len(highlights)}...")
        
        # Calculate duration
        duration = hl.end_time - hl.start_time
        print(f"Highlight duration: {duration:.2f} seconds")
        
        # Skip if too short
        if duration < args.min_highlight_duration:
            print(f"Skipping highlight {i+1} - too short ({duration:.2f}s < {args.min_highlight_duration}s)")
            continue
            
        # Trim if too long
        if duration > args.max_highlight_duration:
            print(f"Trimming highlight {i+1} - too long ({duration:.2f}s > {args.max_highlight_duration}s)")
            duration = args.max_highlight_duration
            
        # Print information about the adaptive duration
        print(f"Using adaptive duration based on content quality")
        print(f"Content score: {hl.score:.2f}")
        if hasattr(hl.scene, 'speech_density'):
            print(f"Speech density: {hl.scene.speech_density:.2f}")
        
        # Extract raw clip
        raw_clip = os.path.join(temp_dir, f"raw_clip_{i}.mp4")
        
        # Use ffmpeg to extract clip
        extract_cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-ss", str(hl.start_time),
            "-t", str(duration),
            "-c:v", "libx264", "-c:a", "aac",
            raw_clip
        ]
        subprocess.run(extract_cmd, check=True)
        
        # Convert to vertical format with padding
        output_file = os.path.join(output_dir, f"short_{i+1}.mp4")
        
        # Generate title from the highlight text
        title_text = generate_title_from_text(hl.text)
        
        # Get captions for the video
        captions = generate_captions(hl, result)
        
        # Create subtitle file
        srt_file = os.path.join(temp_dir, f"captions_{i+1}.srt")
        create_subtitle_file(srt_file, captions)
        
        
        # Clean and prepare title for safety
        simple_title = title_text.replace("'", "").replace("\"", "").replace(",", "").replace(":", "")
        if not simple_title:
            simple_title = f"HIGHLIGHT {i+1}"
        
        # Make title more engaging
        if not simple_title.isupper():
            simple_title = simple_title.upper()
        
        # Get a representative caption from the highlight
        caption_text = ""
        if hl.text and len(hl.text) > 10:
            # Use a portion of the text with proper ending
            words = hl.text.split()
            if len(words) > 5:
                # Take enough words to make a good caption
                word_count = min(12, len(words))
                caption_text = ' '.join(words[:word_count])
                if len(words) > word_count:
                    caption_text += "..."
            else:
                caption_text = hl.text
        else:
            # Varied captions for more engagement
            captions = [
                "Watch this amazing highlight!",
                "Don't miss this key moment!",
                "This is worth watching!",
                "Check this out!",
                "Important point here!"
            ]
            caption_text = captions[i % len(captions)]
        
        # Simplify caption for safety
        caption_text = caption_text.replace("'", "").replace("\"", "").replace(",", "").replace(":", "")
        
        # One-step process with both text overlays
        # Title at top, caption at bottom
        filter_complex = (
            f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease," +
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2," +
            # Add title at top with black background
            f"drawbox=x=0:y=0:w={target_width}:h=120:color=black@0.8:t=fill," +
            f"drawtext=text='{simple_title}':fontsize=48:fontcolor=white:x=(w-text_w)/2:y=60-th/2," +
            # Add caption at bottom with black background
            f"drawbox=x=0:y=h-120:w={target_width}:h=120:color=black@0.8:t=fill," +
            f"drawtext=text='{caption_text}':fontsize=36:fontcolor=white:x=(w-text_w)/2:y=h-60-th/2"
        )
        
        output_file = os.path.join(output_dir, f"short_{i+1}.mp4")
        
        vertical_cmd = [
            "ffmpeg", "-y", "-i", raw_clip,
            "-vf", filter_complex,
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            output_file
        ]
        
        try:
            subprocess.run(vertical_cmd, check=True)
            print(f"Successfully created short video {i+1} with title and captions")
        except subprocess.CalledProcessError as e:
            print(f"Error creating video {i+1}: {e}")
            # Fallback to even simpler approach without text
            print(f"Trying fallback approach for video {i+1}...")
            fallback_cmd = [
                "ffmpeg", "-y", "-i", raw_clip,
                "-vf", f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease," +
                       f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2",
                "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                output_file
            ]
            subprocess.run(fallback_cmd, check=True)
            print(f"Created video {i+1} without overlays (fallback)")
        
        print(f"Created short video {i+1}: {output_file}")
    
    # Clean up temporary directory
    shutil.rmtree(temp_dir)
    
    # Count generated shorts
    shorts_count = len([f for f in os.listdir(output_dir) if f.startswith("short_") and f.endswith(".mp4")])
    
    print(f"[7/7] Generated {shorts_count} shorts videos in: {os.path.abspath(output_dir)}")
    print("Pipeline complete.")

if __name__ == "__main__":
    main()
