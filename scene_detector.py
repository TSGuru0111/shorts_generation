from typing import List, Tuple, Optional
import cv2
import numpy as np

class Scene:
    def __init__(self, start_time: float, end_time: float, 
                 speech_segments: Optional[List[Tuple[float, float]]] = None):
        self.start_time = start_time
        self.end_time = end_time
        self.duration = end_time - start_time
        self.speech_segments = speech_segments or []
        self.speech_duration = sum(end - start for start, end in self.speech_segments)
        self.speech_density = self.speech_duration / self.duration if self.duration > 0 else 0

class SceneDetector:
    def __init__(self, min_scene_len: float = 0.5, threshold: int = 27):
        """
        Initialize scene detector with configurable parameters.
        
        Args:
            min_scene_len: Minimum scene length in seconds
            threshold: Threshold for content change detection (0-255)
        """
        self.min_scene_len = min_scene_len
        self.threshold = threshold

    def detect_scenes(self, video_path: str, speech_segments: List[Tuple[float, float]] = None) -> List[Scene]:
        """Detect scenes in a video using frame differences and speech segments"""
        try:
            # Open video file
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = frame_count / fps
            
            print(f"Processing video: {frame_count} frames at {fps} fps")
            print(f"Using optimized scene detection (sampling frames)")
            
            # For long videos, we'll sample frames aggressively
            # Process 1 frame per second for faster detection
            frame_sample_rate = max(1, int(fps))
            print(f"Sampling 1 frame every {frame_sample_rate} frames")
            
            scenes = []
            current_scene_start = 0
            last_frame = None
            frame_idx = 0
            actual_frame_idx = 0
            frame_threshold = self.threshold / 255.0  # Convert threshold to 0-1 range
            min_scene_frames = int(self.min_scene_len * fps)
            
            while actual_frame_idx < frame_count:
                # Set frame position
                cap.set(cv2.CAP_PROP_POS_FRAMES, actual_frame_idx)
                ret, frame = cap.read()
                if not ret:
                    break
                
                current_time = actual_frame_idx / fps
                
                # Convert frame to grayscale and resize for faster processing
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.resize(gray, (320, 180))  # Reduce resolution for faster comparison
                
                if last_frame is not None:
                    # Calculate frame difference using numpy operations
                    diff = np.mean(np.abs(gray.astype(np.float32) - last_frame.astype(np.float32)))
                    
                    # Scene change detection
                    if diff > frame_threshold and actual_frame_idx - current_scene_start >= min_scene_frames:
                        scene_start_time = current_scene_start / fps
                        scene_end_time = current_time
                        
                        # Find overlapping speech segments
                        scene_speech = []
                        if speech_segments:
                            for speech_start, speech_end in speech_segments:
                                if speech_start <= scene_end_time and speech_end >= scene_start_time:
                                    overlap_start = max(scene_start_time, speech_start)
                                    overlap_end = min(scene_end_time, speech_end)
                                    scene_speech.append((overlap_start, overlap_end))
                        
                        scenes.append(Scene(scene_start_time, scene_end_time, scene_speech))
                        current_scene_start = actual_frame_idx
                
                last_frame = gray
                frame_idx += 1
                actual_frame_idx += frame_sample_rate
                
                # Progress update
                if frame_idx % 5 == 0:  # Update more frequently
                    progress = actual_frame_idx / frame_count * 100
                    print(f"Processing: {actual_frame_idx}/{frame_count} frames ({progress:.1f}%) - Found {len(scenes)} scenes")
            
            # Add final scene
            if current_scene_start < frame_count - 1:
                scene_start_time = current_scene_start / fps
                scene_end_time = duration
                
                # Find overlapping speech segments for final scene
                scene_speech = []
                if speech_segments:
                    for speech_start, speech_end in speech_segments:
                        if speech_start <= scene_end_time and speech_end >= scene_start_time:
                            overlap_start = max(scene_start_time, speech_start)
                            overlap_end = min(scene_end_time, speech_end)
                            scene_speech.append((overlap_start, overlap_end))
                
                scenes.append(Scene(scene_start_time, scene_end_time, scene_speech))
            
            cap.release()
            return scenes
        except Exception as e:
            print(f"Error detecting scenes: {e}")
            return []

    def merge_short_scenes(self, scenes: List[Scene], min_duration: float = 1.0) -> List[Scene]:
        """
        Merge scenes that are too short with adjacent scenes.
        
        Args:
            scenes: List of Scene objects
            min_duration: Minimum duration in seconds
        
        Returns:
            List of merged Scene objects
        """
        if not scenes:
            return []

        merged = []
        current = scenes[0]

        for next_scene in scenes[1:]:
            if current.duration < min_duration:
                # Merge with next scene
                speech_segments = current.speech_segments + next_scene.speech_segments
                current = Scene(
                    current.start_time,
                    next_scene.end_time,
                    speech_segments
                )
            else:
                merged.append(current)
                current = next_scene

        # Don't forget the last scene
        if current.duration >= min_duration:
            merged.append(current)
        elif merged:
            # Merge with previous scene
            prev = merged.pop()
            speech_segments = prev.speech_segments + current.speech_segments
            merged.append(Scene(
                prev.start_time,
                current.end_time,
                speech_segments
            ))
        else:
            # Single scene case
            merged.append(current)

        return merged
