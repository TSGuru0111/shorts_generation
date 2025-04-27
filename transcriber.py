import whisper
import torch
from typing import Dict, List, Tuple
import numpy as np

class TranscriptionResult:
    def __init__(self, segments, words):
        self.segments = segments
        self.words = words
        print(f"Initialized TranscriptionResult with {len(segments)} segments and {len(words)} words")
        
    def get_words_in_timerange(self, start_time: float, end_time: float) -> List[dict]:
        """Get words that fall within the given time range"""
        matching_words = []
        for segment in self.segments:
            # Check if segment overlaps with the time range
            if segment['start'] <= end_time and segment['end'] >= start_time:
                # If the segment has word-level timestamps
                if 'words' in segment:
                    for word in segment['words']:
                        if start_time <= word['start'] <= end_time:
                            matching_words.append(word)
                else:
                    # If no word-level timestamps, use the segment text
                    matching_words.append({
                        'text': segment['text'],
                        'start': segment['start'],
                        'end': segment['end']
                    })
        return matching_words

class WhisperTranscriber:
    def __init__(self, model_size="base", device=None):
        """Initialize the transcriber with the specified model size"""
        try:
            # Keep it simple - use CPU by default
            self.device = "cpu"
            if device == "cuda" and torch.cuda.is_available():
                self.device = "cuda"
                print(f"Using CUDA device: {torch.cuda.get_device_name(0)}")
            # Load model with optimized settings
            print(f"Loading Whisper {model_size} model...")
            self.model = whisper.load_model(model_size, device='cuda' if torch.cuda.is_available() else 'cpu')
            self.model.eval()  # Set to evaluation mode for better performance
            print(f"Initialization complete on {'GPU' if torch.cuda.is_available() else 'CPU'}")
            if self.device == "cuda":
                self.model = self.model.to(self.device)
                print("Model moved to CUDA device")
            
            # Enable half-precision floating point if on GPU
            if self.device == "cuda":
                print("Converting model to half precision...")
                self.model = self.model.half()
            
            print("Initialization complete")
        except Exception as e:
            import traceback
            print(f"Error during initialization: {str(e)}")
            print("Full traceback:")
            print(traceback.format_exc())
            raise

    def transcribe(self, audio_path: str, language: str = None) -> TranscriptionResult:
        """
        Transcribe audio file using Whisper model.
        Returns a TranscriptionResult object containing segments and word-level timestamps.
        """
        try:
            # First try to load the audio file
            import ffmpeg
            try:
                probe = ffmpeg.probe(audio_path)
                duration = float(probe['format']['duration'])
                print(f"Processing audio file of {duration:.1f} seconds...")
            except ffmpeg.Error as e:
                print(f"Error loading audio file: {e.stderr.decode() if e.stderr else str(e)}")
                return TranscriptionResult([], [])
                
            # Now attempt transcription with progress updates
            print("Starting transcription...")
            try:
                # Optimize transcription settings for speed
                result = self.model.transcribe(
                    audio_path,
                    language=language,
                    word_timestamps=True,
                    verbose=False,
                    beam_size=3,  # Reduce beam size for faster processing
                    best_of=3,   # Reduce candidates for faster processing
                    condition_on_previous_text=False  # Disable for faster processing
                )
                
                # Extract segments and words
                segments = []
                words = []
                
                for segment in result["segments"]:
                    text = str(segment.get("text", "")).strip()
                    if text:
                        # Add segment
                        segments.append({
                            "start": float(segment.get("start", 0)),
                            "end": float(segment.get("end", 0)),
                            "text": text
                        })
                        
                        # Add words if available
                        if "words" in segment:
                            for word in segment["words"]:
                                if isinstance(word, dict) and "start" in word and "end" in word:
                                    if word["end"] - word["start"] > 0:  # Filter out zero-duration words
                                        word_dict = {
                                            "text": str(word.get("text", "")).strip(),
                                            "start": float(word["start"]),
                                            "end": float(word["end"]),
                                            "confidence": float(segment.get("confidence", 0.0))
                                        }
                                        words.append(word_dict)
                
                print(f"Transcription complete: {len(segments)} segments found")
                if segments:
                    print(f"Sample text: {segments[0]['text'][:100]}...")
                
                return TranscriptionResult(segments, words)
            except Exception as e:
                print(f"Transcription failed: {str(e)}")
                return TranscriptionResult([], [])
        except Exception as e:
            print(f"Error during transcription: {e}")
            # Return empty result if transcription fails
            return TranscriptionResult([], [])

    def get_speech_segments(self, result: TranscriptionResult, 
                          min_segment_duration: float = 1.0,
                          max_segment_duration: float = 60.0) -> List[Tuple[float, float]]:
        """
        Extract meaningful speech segments from transcription, avoiding breaks mid-sentence.
        
        Args:
            result: TranscriptionResult from transcribe()
            min_segment_duration: Minimum duration for a segment in seconds
            max_segment_duration: Maximum duration for a segment in seconds
        
        Returns:
            List of (start_time, end_time) tuples
        """
        segments = []
        current_start = None
        current_duration = 0

        for segment in result.segments:
            if current_start is None:
                current_start = segment["start"]
                
            segment_duration = segment["end"] - segment["start"]
            
            # Check if adding this segment would exceed max duration
            if current_duration + segment_duration > max_segment_duration:
                segments.append((current_start, current_start + current_duration))
                current_start = segment["start"]
                current_duration = segment_duration
            else:
                current_duration += segment_duration

            # If we hit a long pause or end of segments, close the current segment
            next_segment = segment.get("next")
            if (next_segment and next_segment["start"] - segment["end"] > 1.0) or not next_segment:
                if current_duration >= min_segment_duration:
                    segments.append((current_start, current_start + current_duration))
                    current_start = None
                    current_duration = 0

        return segments
