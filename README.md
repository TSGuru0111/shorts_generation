# YouTube Shorts Generator

A fully automated pipeline to transform any YouTube video into a series of polished, viral-ready vertical shorts for TikTok, Instagram Reels, and YouTube Shorts. The tool analyzes video content, extracts the most engaging segments, and creates multiple short-form videos with titles and captions.

## Features
- **Intelligent Content Analysis**: Automatically identifies the most engaging parts of any YouTube video
- **Variable Duration**: Creates shorts of varying lengths (30-90 seconds) based on content quality
- **Vertical Format**: Optimized 9:16 aspect ratio (1080x1920) for all social platforms
- **Title & Caption Overlays**: Automatically generates and adds titles and captions
- **Multi-platform Support**: Downloads from YouTube using various methods (yt-dlp, PyTube, etc.)
- **Speech Recognition**: Uses Whisper for accurate transcription with word-level timestamps
- **Scene Detection**: Identifies natural scene changes for better clip selection
- **Viral Content Selection**: Scores content based on engagement potential

## Setup
1. Clone this repository:
   ```bash
   git clone https://github.com/TSGuru0111/shorts_generation.git
   cd shorts_generation
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. (Optional) Set up configuration files:
   - Copy `.env.template` to `.env` and add your API keys if needed
   - Copy `client_secrets.json.template` to `client_secrets.json` for YouTube API access

## Usage

Generate shorts from any YouTube video:

```bash
python main.py --youtube-url <YOUTUBE_URL> [OPTIONS]
```

Options:
- `--min-highlight-duration`: Minimum duration for shorts (default: 30s)
- `--max-highlight-duration`: Maximum duration for shorts (default: 90s)
- `--max-highlights`: Maximum number of shorts to generate (default: 5)
- `--whisper-model`: Whisper model size for transcription (tiny, base, small, medium, large)

Example:
```bash
python main.py --youtube-url https://www.youtube.com/watch?v=6Af6b_wyiwI --min-highlight-duration 30 --max-highlight-duration 90 --max-highlights 5
```

The generated shorts will be saved in the `shorts/` directory.

## How It Works

1. **Download**: Downloads the YouTube video using yt-dlp or other fallback methods
2. **Transcribe**: Uses Whisper to transcribe the video with word-level timestamps
3. **Scene Detection**: Identifies scene changes and segments in the video
4. **Highlight Selection**: Selects the most engaging segments based on content quality
5. **Video Processing**: Creates vertical format videos with titles and captions

## Requirements

- Python 3.8+
- FFmpeg (must be installed and available in your PATH)
- Required Python packages (see requirements.txt)

## License

MIT

