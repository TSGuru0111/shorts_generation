import cohere
from typing import List, Tuple, Dict, Optional
import re
from scene_detector import Scene

class Highlight:
    def __init__(self, start_time: float, end_time: float, 
                 score: float, text: str, scene: Scene):
        self.start_time = start_time
        self.end_time = end_time
        self.duration = end_time - start_time
        self.score = score
        self.text = text
        self.scene = scene

class HighlightSelector:
    def __init__(self, cohere_api_key=None, min_duration=30.0, max_duration=90.0):
        """Initialize the highlight selector"""
        self.cohere_api_key = cohere_api_key
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.viral_keywords = [
            'amazing', 'awesome', 'incredible', 'shocking',
            'mind-blowing', 'insane', 'unbelievable', 'viral',
            'trending', 'epic', 'revolutionary', 'game-changing',
            'breakthrough', 'genius', 'masterpiece', 'perfect',
            'stunning', 'extraordinary', 'phenomenal', 'legendary',
            'important', 'key point', 'essential', 'crucial',
            'highlight', 'main idea', 'summary', 'conclusion',
            'therefore', 'result', 'consequently', 'because',
            'explains', 'demonstrates', 'shows', 'proves'
        ]

    def _score_text_with_cohere(self, text: str) -> float:
        """Score text using Cohere's LLM for viral potential."""
        try:
            co = cohere.Client(self.cohere_api_key)
            response = co.generate(
                prompt=f'''Rate the following content for its viral potential on social media platforms like TikTok and Instagram Reels.
                Consider factors like surprise, emotion, relatability, and entertainment value.
                Content: "{text}"
                Rate from 0 to 100, where 100 is extremely viral:''',
                max_tokens=10,
                temperature=0.3,
                model='command'
            )
            
            # Extract numeric score from response
            score_text = response.generations[0].text.strip()
            score_match = re.search(r'\d+', score_text)
            if score_match:
                return float(score_match.group()) / 100
            return 0.5  # Default to middle score if parsing fails
            
        except Exception as e:
            print(f"Cohere scoring failed: {e}")
            return self._score_text_with_keywords(text)

    def _score_text_with_keywords(self, text: str) -> float:
        """Score text based on presence of viral keywords and content quality."""
        text = text.lower()
        
        # Content quality scoring
        word_count = len(text.split())
        sentence_count = len(re.split(r'[.!?]+', text))
        
        # Skip if too short or no real content
        if word_count < 5 or sentence_count == 0:
            return 0.0
        
        # Content density score (words per sentence)
        content_density = word_count / sentence_count
        density_score = min(content_density / 10.0, 1.0)  # Normalize, max at 10 words/sentence
        
        # Keyword scoring with categories
        high_impact_words = sum(1 for kw in self.viral_keywords[:30] if kw.lower() in text)
        content_indicators = sum(1 for kw in self.viral_keywords[30:40] if kw.lower() in text)
        emotional_triggers = sum(1 for kw in self.viral_keywords[40:52] if kw.lower() in text)
        call_to_action = sum(1 for kw in self.viral_keywords[52:] if kw.lower() in text)
        
        # Weight different types of keywords
        keyword_score = (
            high_impact_words * 0.15 +
            content_indicators * 0.25 +
            emotional_triggers * 0.3 +
            call_to_action * 0.2
        )
        
        # Additional quality signals
        has_question = '?' in text
        has_exclamation = '!' in text
        has_number = bool(re.search(r'\d+', text))
        has_quotes = '"' in text or "'" in text
        optimal_length = 10 <= word_count <= 30
        
        quality_score = sum([
            0.2 if has_question else 0,
            0.15 if has_exclamation else 0,
            0.1 if has_number else 0,
            0.15 if has_quotes else 0,
            0.2 if optimal_length else 0
        ])
        
        # Combine all scores with weights
        final_score = (
            keyword_score * 0.4 +
            quality_score * 0.3 +
            density_score * 0.3
        )
        
        return min(final_score, 1.0)

    def _get_text_for_timerange(self, word_timestamps, start_time, end_time):
        text = ""
        for timestamp in word_timestamps:
            if start_time <= timestamp['start'] and timestamp['end'] <= end_time:
                # Use 'word' if present, otherwise fallback to 'text'
                word_text = timestamp.get('word', timestamp.get('text', ''))
                text += word_text + " "
        return text.strip()

    def _score_text(self, text):
        return self._score_text_with_keywords(text)

    def _score_context(self, text):
        # Simple scoring for context, can be improved
        return len(text.split()) / 100.0

    def _score_transitions(self, scenes):
        # Simple scoring for transitions, can be improved
        return len(scenes) / 10.0

    def select_highlights(self, scenes, transcription_result, max_highlights=5):
        """Select the best highlights from the video with adaptive duration based on content"""
        highlights = []
        min_duration = self.min_duration
        max_duration = self.max_duration
        context_window = 5  # Number of seconds to add before/after for context
        
        # Get words from transcription result
        words = transcription_result.words if transcription_result else []
        
        # Group scenes by speech segments with overlapping
        scene_groups = []
        
        # Create overlapping groups to maintain context
        for i in range(len(scenes)):
            current_group = []
            current_duration = 0
            
            # Track speech density to determine optimal clip length
            speech_frames = 0
            total_frames = 0
            
            for j in range(i, len(scenes)):
                # Add scene to current group
                scene = scenes[j]
                current_group.append(scene)
                current_duration += scene.duration
                
                # Track speech density
                if hasattr(scene, 'speech_density'):
                    speech_frames += scene.speech_duration * 30  # Assuming 30fps
                    total_frames += scene.duration * 30
                
                # Calculate adaptive target duration based on content
                # More speech = longer clips, less speech = shorter clips
                speech_density = speech_frames / max(1, total_frames)
                content_richness = min(1.0, len(current_group) / 10)  # More scenes = more variety
                
                # Adaptive duration: 30s for low-content clips, up to 90s for rich content
                adaptive_min = min_duration
                adaptive_max = min(max_duration, min_duration + (max_duration - min_duration) * 
                                  (0.5 * speech_density + 0.5 * content_richness))
                
                # Find natural breaking points (pauses in speech)
                natural_break = False
                if j > i and j < len(scenes) - 1:
                    # Check if there's a pause between this scene and the next
                    if not scene.speech_segments and scenes[j+1].speech_segments:
                        natural_break = True
                
                # Check if we have a good duration with adaptive targets
                good_duration = adaptive_min <= current_duration <= adaptive_max
                
                if good_duration or (current_duration >= adaptive_min and natural_break):
                    # Add context by including nearby scenes
                    context_start = max(0, i - 1)  # One scene before
                    context_end = min(len(scenes), j + 2)  # One scene after
                    
                    full_group = scenes[context_start:context_end]
                    scene_groups.append(full_group)
                
                # Stop if too long
                if current_duration > max_duration:
                    break
        
        # Score each group with context consideration
        scored_groups = []
        for group in scene_groups:
            start_time = max(0, group[0].start_time - context_window)
            end_time = min(group[-1].end_time + context_window, group[-1].end_time)
            duration = end_time - start_time
            
            # Get text for this time range plus context
            text = self._get_text_for_timerange(words, start_time, end_time)
            
            # Score the group based on multiple factors
            content_score = self._score_text(text)
            context_score = self._score_context(text)
            transition_score = self._score_transitions(group)
            
            total_score = (
                content_score * 0.5 +  # Weight for viral/engaging content
                context_score * 0.3 +  # Weight for context/coherence
                transition_score * 0.2  # Weight for smooth transitions
            )
            
            scored_groups.append({
                'scenes': group,
                'start_time': start_time,
                'end_time': end_time,
                'duration': duration,
                'text': text,
                'score': total_score
            })
        
        # Sort by score and ensure no overlap
        scored_groups.sort(key=lambda x: x['score'], reverse=True)
        selected_groups = []
        
        for group in scored_groups:
            # Check for overlap with already selected groups
            overlaps = False
            for selected in selected_groups:
                if (group['start_time'] < selected['end_time'] and 
                    group['end_time'] > selected['start_time']):
                    overlaps = True
                    break
            
            if not overlaps:
                selected_groups.append(group)
                if len(selected_groups) >= max_highlights:
                    break
        
        # Create highlights from selected groups
        for group in selected_groups:
            highlights.append(Highlight(
                start_time=group['start_time'],
                end_time=group['end_time'],
                score=group['score'],
                text=group['text'],
                scene=group['scenes'][0]
            ))
        
        return highlights
