// Main application logic for Telegram Mini App

let playerWrapper = null;
let startTime = null;
let endTime = null;
let currentTimeUpdateInterval = null;
let audioOnly = false;
let videoDuration = 0;
let isScrubbing = false;
let isUserScrubbing = false;
let lastSyncedVideoTime = 0;
let lastVideoTime = 0;
let isVideoPlaying = false;
let lastSyncTime = 0;
let fineScrubberCurrentTime = 0;
let stadiometerDragStartX = 0;
let stadiometerDragStartTranslate = 0;
let isStadiometerDragging = false;
let lastSeekTime = 0;
const SEEK_THROTTLE_MS = 100; // Throttle seeks to once per 100ms during drag

// Initialize Telegram WebApp
const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

// Format seconds to MM:SS or HH:MM:SS with millisecond precision
function formatTime(seconds) {
    if (seconds === null || seconds === undefined) {
        return '0:00.000';
    }
    const totalSeconds = Math.floor(seconds);
    const milliseconds = Math.floor((seconds - totalSeconds) * 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const secsRemainder = totalSeconds % 60;
    
    if (hours > 0) {
        return `${hours}:${String(minutes).padStart(2, '0')}:${String(secsRemainder).padStart(2, '0')}.${String(milliseconds).padStart(3, '0')}`;
    }
    return `${minutes}:${String(secsRemainder).padStart(2, '0')}.${String(milliseconds).padStart(3, '0')}`;
}

// Update current time display
function updateCurrentTimeDisplay() {
    if (playerWrapper) {
        const current = playerWrapper.getCurrentTime();
        document.getElementById('current-time').textContent = formatTime(current);
        
        // Keep fine scrubber in sync with video playback whenever
        // the user is not actively dragging our scrubber
        if (!isUserScrubbing && !isScrubbing) {
            syncScrubbersToVideoTime(current);
            lastSyncedVideoTime = current;
            lastSyncTime = Date.now();
        }
        lastVideoTime = current;
    }
}

// Update timestamp displays
function updateTimestampDisplays() {
    document.getElementById('start-time').textContent = startTime !== null ? formatTime(startTime) : 'Not set';
    document.getElementById('end-time').textContent = endTime !== null ? formatTime(endTime) : 'Not set';
    
    // Enable confirm button if both timestamps are set
    const confirmBtn = document.getElementById('confirm-btn');
    if (startTime !== null && endTime !== null && startTime < endTime) {
        confirmBtn.disabled = false;
    } else {
        confirmBtn.disabled = true;
    }
    
    // Update button text based on audio/video mode
    if (audioOnly) {
        confirmBtn.textContent = 'Confirm & Download Audio';
    } else {
        confirmBtn.textContent = 'Confirm & Download Video';
    }
}

// Extract video ID from URL
function extractVideoId(url) {
    if (!url) return null;
    
    // Handle various YouTube URL formats
    const patterns = [
        /(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([^&\n?#]+)/,
        /youtube\.com\/watch\?.*v=([^&\n?#]+)/
    ];
    
    for (const pattern of patterns) {
        const match = url.match(pattern);
        if (match && match[1]) {
            return match[1];
        }
    }
    
    return null;
}

// Get video URL from Telegram WebApp
function getVideoUrl() {
    // Try to get from initData
    const initData = tg.initData;
    if (initData) {
        try {
            const params = new URLSearchParams(initData);
            const url = params.get('video_url');
            if (url) return decodeURIComponent(url);
        } catch (e) {
            console.error('Error parsing initData:', e);
        }
    }
    
    // Try to get from URL parameters
    const urlParams = new URLSearchParams(window.location.search);
    const url = urlParams.get('video_url');
    if (url) return decodeURIComponent(url);
    
    return null;
}

// Show error message
function showError(message) {
    const errorEl = document.getElementById('error-message');
    errorEl.textContent = message;
    errorEl.style.display = 'block';
}

// Hide error message
function hideError() {
    document.getElementById('error-message').style.display = 'none';
}

// Initialize scrubbers
function initScrubbers() {
    const stadiometerViewport = document.getElementById('fine-scrubber-viewport');
    
    if (!stadiometerViewport) {
        console.error('Scrubber elements not found');
        return;
    }
    
    // Set initial range (will be updated when duration loads)
    if (videoDuration > 0) {
        updateFineScrubberRange();
    }
    
    // Initialize stadiometer drag handlers
    initStadiometerDragHandlers();
}


// Initialize stadiometer drag handlers
function initStadiometerDragHandlers() {
    const viewport = document.getElementById('fine-scrubber-viewport');
    if (!viewport) return;
    
    viewport.addEventListener('mousedown', handleStadiometerDragStart);
    viewport.addEventListener('touchstart', handleStadiometerDragStart);
    
    document.addEventListener('mousemove', handleStadiometerDrag);
    document.addEventListener('touchmove', handleStadiometerDrag);
    document.addEventListener('mouseup', handleStadiometerDragEnd);
    document.addEventListener('touchend', handleStadiometerDragEnd);
}

// Handle stadiometer drag start
function handleStadiometerDragStart(e) {
    if (e.target.closest('#fine-scrubber-viewport')) {
        isStadiometerDragging = true;
        isUserScrubbing = true;
        const viewport = document.getElementById('fine-scrubber-viewport');
        const scale = document.getElementById('fine-scrubber-scale');
        
        if (!viewport || !scale) return;
        
        const rect = viewport.getBoundingClientRect();
        const clientX = e.touches ? e.touches[0].clientX : e.clientX;
        stadiometerDragStartX = clientX;
        
        const currentTransform = scale.style.transform;
        const match = currentTransform.match(/translateX\(([^)]+)\)/);
        stadiometerDragStartTranslate = match ? parseFloat(match[1]) : 0;
        
        // Calculate time at click position and seek immediately when drag starts (even if video hasn't played)
        if (playerWrapper && videoDuration > 0) {
            const viewportWidth = viewport.offsetWidth;
            const visibleTimeRange = 30;
            const pixelsPerSecond = viewportWidth / visibleTimeRange;
            const scaleWidth = videoDuration * pixelsPerSecond;
            
            // Calculate click position relative to viewport
            const clickX = clientX - rect.left;
            // Calculate time at click position
            // Scale's time 0 is at viewport position translateX (translateX moves element right when positive)
            // So time at clickX = (clickX - translateX) / pixelsPerSecond
            const clickTime = (clickX - stadiometerDragStartTranslate) / pixelsPerSecond;
            const clampedClickTime = Math.max(0, Math.min(videoDuration, clickTime));
            
            // Update current time and seek
            fineScrubberCurrentTime = clampedClickTime;
            isScrubbing = true;
            playerWrapper.seekTo(clampedClickTime, true).then(() => {
                isScrubbing = false;
            }).catch(() => {
                isScrubbing = false;
            });
            lastSeekTime = Date.now();
            updateStadiometerTimeDisplay();
        }
        
        e.preventDefault();
    }
}

// Handle stadiometer drag
function handleStadiometerDrag(e) {
    if (!isStadiometerDragging) return;
    
    const viewport = document.getElementById('fine-scrubber-viewport');
    const scale = document.getElementById('fine-scrubber-scale');
    
    if (!viewport || !scale || videoDuration <= 0) return;
    
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const deltaX = clientX - stadiometerDragStartX;
    const viewportWidth = viewport.offsetWidth;
    const visibleTimeRange = 30; // 30 seconds visible
    
    // Calculate pixels per second (based on viewport showing 30 seconds)
    const pixelsPerSecond = viewportWidth / visibleTimeRange;
    const scaleWidth = videoDuration * pixelsPerSecond;
    
    // Calculate new translate value
    // When dragging right (positive deltaX): scale moves right, showing earlier times
    // When dragging left (negative deltaX): scale moves left, showing later times
    const newTranslate = stadiometerDragStartTranslate + deltaX;
    
    // Calculate what time is at the viewport center with this translate
    // The scale's left edge (time 0) is positioned at translateX relative to viewport left
    // Viewport center is at viewportWidth/2 from viewport left
    // Time at viewport center = (viewportWidth/2 - translateX) / pixelsPerSecond
    const centerTime = (viewportWidth / 2 - newTranslate) / pixelsPerSecond;
    
    // Clamp time to valid range (0 to videoDuration)
    const clampedTime = Math.max(0, Math.min(videoDuration, centerTime));
    
    // Calculate translate needed to put clamped time at center
    // Position of clamped time on scale = clampedTime * pixelsPerSecond
    // To center it: translateX = viewportWidth/2 - timePositionOnScale
    const timePositionOnScale = clampedTime * pixelsPerSecond;
    const clampedTranslate = (viewportWidth / 2) - timePositionOnScale;
    
    // Clamp translate to keep viewport within scale bounds
    // Symmetrical clamping: allow centering both start (time 0) and end (videoDuration)
    // maxTranslate: allows centering time 0 (translate = viewportWidth/2)
    // minTranslate: allows centering videoDuration (translate = viewportWidth/2 - scaleWidth)
    const maxTranslate = viewportWidth / 2;
    const minTranslate = (viewportWidth / 2) - scaleWidth;
    const finalTranslate = Math.max(minTranslate, Math.min(maxTranslate, clampedTranslate));
    
    scale.style.transform = `translateX(${finalTranslate}px)`;
    fineScrubberCurrentTime = clampedTime;
    
    // Seek video during drag (throttled to avoid too many seek calls)
    const now = Date.now();
    if (playerWrapper && (now - lastSeekTime) >= SEEK_THROTTLE_MS) {
        isScrubbing = true;
        playerWrapper.seekTo(clampedTime, true).then(() => {
            isScrubbing = false;
        }).catch(() => {
            isScrubbing = false;
        });
        lastSeekTime = now;
    }
    
    // Update display
    updateStadiometerTimeDisplay();
    
    e.preventDefault();
}

// Handle stadiometer drag end
function handleStadiometerDragEnd(e) {
    if (!isStadiometerDragging) return;
    
    isStadiometerDragging = false;
    isUserScrubbing = false;
    
    // Final seek to ensure we're at the exact position (in case throttling skipped the last one)
    if (playerWrapper && fineScrubberCurrentTime >= 0) {
        isScrubbing = true;
        playerWrapper.seekTo(fineScrubberCurrentTime, true).then(() => {
            isScrubbing = false;
        }).catch(() => {
            isScrubbing = false;
        });
    }
    
    lastSeekTime = 0; // Reset throttle for next drag
    
    e.preventDefault();
}

// Generate time labels for stadiometer scale
// CSS gradient provides the visual ruler pattern, but we need HTML labels for time values
function generateStadiometerScale(pixelsPerSecond, scaleWidth) {
    const scale = document.getElementById('fine-scrubber-scale');
    if (!scale || videoDuration <= 0 || !pixelsPerSecond) return;

    // Clear existing labels
    const existingLabels = scale.querySelectorAll('.stadiometer-time-label');
    existingLabels.forEach(label => label.remove());

    // Choose appropriate label interval based on video duration
    let labelInterval; // seconds between labels
    if (videoDuration <= 60) {          // <= 1 min
        labelInterval = 5;
    } else if (videoDuration <= 5 * 60) { // <= 5 min
        labelInterval = 10;
    } else if (videoDuration <= 20 * 60) { // <= 20 min
        labelInterval = 30;
    } else {
        labelInterval = 60;             // 1 minute labels for long videos
    }

    // Create time labels at regular intervals
    for (let time = 0; time <= videoDuration + 0.001; time += labelInterval) {
        const label = document.createElement('div');
        label.className = 'stadiometer-time-label';
        label.textContent = formatTime(time);
        
        // Position label: time * pixelsPerSecond
        const position = time * pixelsPerSecond;
        label.style.position = 'absolute';
        label.style.left = `${position}px`;
        label.style.transform = 'translateX(-50%)'; // Center label on its position
        label.style.top = '2px'; // Position at top of scale
        
        scale.appendChild(label);
    }
}

// Update fine scrubber range (stadiometer version)
// Uses FULL video duration scale with 30-second viewport
function updateFineScrubberRange(preserveFineValue = false) {
    const viewport = document.getElementById('fine-scrubber-viewport');
    const scale = document.getElementById('fine-scrubber-scale');
    if (!viewport || !scale || videoDuration === 0) return;
    
    // Determine center time
    let centerTime;
    if (preserveFineValue && fineScrubberCurrentTime >= 0 && fineScrubberCurrentTime <= videoDuration) {
        centerTime = fineScrubberCurrentTime;
    } else {
        // When not preserving, use fineScrubberCurrentTime if it's valid, otherwise default to 0
        if (fineScrubberCurrentTime >= 0 && fineScrubberCurrentTime <= videoDuration) {
            centerTime = fineScrubberCurrentTime;
        } else {
            centerTime = 0; // Default to start of video
        }
    }
    
    // Clamp center time to video bounds
    fineScrubberCurrentTime = Math.max(0, Math.min(videoDuration, centerTime));
    
    // Wait for viewport to have width, then generate scale and position viewport
    requestAnimationFrame(() => {
        // Double-check viewport width is available
        const viewportWidth = viewport.offsetWidth || 300;
        if (viewportWidth === 0) {
            // Retry if viewport not ready yet
            setTimeout(() => {
                updateFineScrubberRange(preserveFineValue);
            }, 50);
            return;
        }
        
        const visibleTimeRange = 30; // 30 seconds visible
        const pixelsPerSecond = viewportWidth / visibleTimeRange;
        const scaleWidth = videoDuration * pixelsPerSecond;
        
        // Ensure the scale element spans the full video duration so the CSS
        // gradient ruler repeats across the entire timeline, not just the first 30s
        scale.style.width = `${scaleWidth}px`;
        
        // Generate time labels positioned at regular intervals
        generateStadiometerScale(pixelsPerSecond, scaleWidth);
        
        // Calculate where center time is on the full-duration scale
        const centerPositionOnScale = fineScrubberCurrentTime * pixelsPerSecond;
        
        // Calculate translate needed to put center time at viewport center
        // Time at viewport center = (viewportWidth/2 - translateX) / pixelsPerSecond
        // So: translateX = viewportWidth/2 - centerPositionOnScale
        const viewportCenter = viewportWidth / 2;
        let translateX = viewportCenter - centerPositionOnScale;
        
        // Clamp translate to keep viewport within scale bounds
        // Symmetrical clamping: allow centering both start (time 0) and end (videoDuration)
        // maxTranslate: allows centering time 0 (translate = viewportWidth/2)
        // minTranslate: allows centering videoDuration (translate = viewportWidth/2 - scaleWidth)
        const maxTranslate = viewportWidth / 2;
        const minTranslate = (viewportWidth / 2) - scaleWidth;
        translateX = Math.max(minTranslate, Math.min(maxTranslate, translateX));
        
        scale.style.transform = `translateX(${translateX}px)`;
        
        // Update displays
        updateStadiometerTimeDisplay();
        updateScrubberTimeDisplays();
    });
}


// Update stadiometer time display
function updateStadiometerTimeDisplay() {
    const fineTimeDisplay = document.getElementById('fine-time');
    if (fineTimeDisplay) {
        fineTimeDisplay.textContent = formatTime(fineScrubberCurrentTime);
    }
}

// Update scrubber time displays
function updateScrubberTimeDisplays() {
    // Update stadiometer time display
    updateStadiometerTimeDisplay();
}

// Sync scrubber to video's current time (only called when user scrubs on YouTube player)
function syncScrubbersToVideoTime(videoTime) {
    if (!playerWrapper || videoDuration === 0) return;
    
    const viewport = document.getElementById('fine-scrubber-viewport');
    const scale = document.getElementById('fine-scrubber-scale');
    
    if (!viewport || !scale) return;
    
    // Update fine scrubber range and center it on the new video time
    // (When user scrubs on YouTube player, we want to follow that position)
    fineScrubberCurrentTime = Math.max(0, Math.min(videoDuration, videoTime));
    updateFineScrubberRange(false); // Don't preserve - user scrubbed on YouTube
    
    updateScrubberTimeDisplays();
}

// Get current scrubber position (from fine scrubber for precision)
function getCurrentScrubberTime() {
    // Use stadiometer current time
    if (fineScrubberCurrentTime >= 0) {
        return fineScrubberCurrentTime;
    }
    // Fallback to player time
    if (playerWrapper) {
        return playerWrapper.getCurrentTime();
    }
    return 0;
}

// Initialize player
async function initPlayer() {
    try {
        const videoUrl = getVideoUrl();
        if (!videoUrl) {
            showError('No video URL provided. Please open this app from the bot.');
            return;
        }
        
        const videoId = extractVideoId(videoUrl);
        if (!videoId) {
            showError('Invalid YouTube URL. Please provide a valid YouTube video URL.');
            return;
        }
        
        hideError();
        
        // Create player
        playerWrapper = await createYouTubePlayer(videoId);
        
        // Add player to container
        const container = document.getElementById('player-container');
        container.innerHTML = '';
        container.appendChild(playerWrapper.container);
        
        // Wait for player to be ready and get duration
        await playerWrapper.player;
        
        // Try to get duration, with retry if not immediately available
        let retries = 10;
        while (retries > 0 && (videoDuration === 0 || isNaN(videoDuration))) {
            const duration = await playerWrapper.getDuration();
            if (duration > 0 && !isNaN(duration)) {
                videoDuration = duration;
                break;
            }
            await new Promise(resolve => setTimeout(resolve, 200));
            retries--;
        }
        
        // Set up playback state tracking
        window.updateVideoPlaybackState = (playing) => {
            isVideoPlaying = playing;
        };
        
        // Initialize scrubbers with duration
        initScrubbers();
        
        // Update ranges with actual duration
        if (videoDuration > 0 && !isNaN(videoDuration)) {
            // Initialize fine scrubber at video start (0:00.000)
            fineScrubberCurrentTime = 0;
            updateFineScrubberRange(false); // Don't preserve - explicitly center at 0
            console.log('Video duration loaded:', videoDuration, 'seconds');
        } else {
            console.error('Failed to load video duration');
            // Retry getting duration after a delay
            setTimeout(async () => {
                if (videoDuration === 0 || isNaN(videoDuration)) {
                    const duration = await playerWrapper.getDuration();
                    if (duration > 0 && !isNaN(duration)) {
                        videoDuration = duration;
                        fineScrubberCurrentTime = 0; // Initialize at start
                        updateFineScrubberRange(false); // Don't preserve - explicitly center at 0
                        console.log('Video duration loaded (retry):', videoDuration, 'seconds');
                    }
                }
            }, 1000);
        }
        
        // Start updating current time display
        if (currentTimeUpdateInterval) {
            clearInterval(currentTimeUpdateInterval);
        }
        currentTimeUpdateInterval = setInterval(updateCurrentTimeDisplay, 100);
        
    } catch (error) {
        console.error('Error initializing player:', error);
        showError(`Failed to load video: ${error.message}`);
    }
}

// Set start timestamp
function setStartTime() {
    startTime = getCurrentScrubberTime();
    updateTimestampDisplays();
}

// Set end timestamp
function setEndTime() {
    endTime = getCurrentScrubberTime();
    updateTimestampDisplays();
}

// Reset timestamps
function resetTimestamps() {
    startTime = null;
    endTime = null;
    updateTimestampDisplays();
}

// Send data to bot
function sendDataToBot() {
    console.log('=== sendDataToBot() CALLED ===');
    console.log('DEBUG: startTime:', startTime, 'endTime:', endTime);
    console.log('DEBUG: playerWrapper exists:', !!playerWrapper);
    
    if (startTime === null || endTime === null) {
        console.log('ERROR: Timestamps not set');
        showError('Please set both start and end timestamps.');
        return;
    }
    
    if (startTime >= endTime) {
        console.log('ERROR: Start time >= end time');
        showError('Start time must be before end time.');
        return;
    }
    
    if (!playerWrapper) {
        console.log('ERROR: Player not initialized');
        showError('Player not initialized.');
        return;
    }
    
    const videoUrl = getVideoUrl();
    console.log('DEBUG: videoUrl:', videoUrl);
    const videoId = extractVideoId(videoUrl);
    console.log('DEBUG: videoId:', videoId);
    
    // Get chat_id from URL parameters
    const urlParams = new URLSearchParams(window.location.search);
    const chatId = urlParams.get('chat_id');
    console.log('DEBUG: chatId from URL:', chatId);
    console.log('DEBUG: Full URL:', window.location.href);
    
    if (!chatId) {
        console.log('ERROR: Chat ID not found');
        showError('Chat ID not found. Please open the mini app from the bot.');
        return;
    }
    
    // For InlineKeyboardButton, we need to use answerWebAppQuery
    // Get query_id from initData (only exists when opened via InlineKeyboardButton)
    const initData = tg.initDataUnsafe || {};
    const queryId = initData.query_id;
    console.log('DEBUG: initData:', initData);
    console.log('DEBUG: queryId from initData:', queryId);
    
    const data = {
        videoId: videoId,
        videoUrl: videoUrl,
        start: startTime,
        end: endTime,
        startFloat: startTime,
        endFloat: endTime,
        chatId: chatId,
        audioOnly: audioOnly
    };
    
    // Send to our endpoint which will call answerWebAppQuery
    const confirmBtn = document.getElementById('confirm-btn');
    const originalText = confirmBtn.textContent;
    confirmBtn.disabled = true;
    confirmBtn.textContent = 'Sending...';
    
    // Use absolute URL to avoid routing issues
    const endpoint = window.location.origin + '/api/mini_app/submit';
    const payload = {query_id: queryId || null, data: data};
    
    console.log('=== ABOUT TO SEND FETCH ===');
    console.log('Sending to:', endpoint);
    console.log('Payload:', JSON.stringify(payload));
    console.log('Payload size:', JSON.stringify(payload).length, 'bytes');
    
    const fetchPromise = fetch(endpoint, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    });
    
    console.log('=== FETCH PROMISE CREATED ===');
    
    fetchPromise
    .then(response => {
        console.log('=== FETCH RESPONSE RECEIVED ===');
        console.log('Response status:', response.status);
        console.log('Response ok:', response.ok);
        if (!response.ok) {
            return response.text().then(text => {
                console.error('Response error text:', text);
                throw new Error(`HTTP ${response.status}: ${text}`);
            });
        }
        return response.json();
    })
    .then(result => {
        console.log('=== FETCH SUCCESS ===');
        console.log('Result:', result);
        confirmBtn.disabled = false;
        confirmBtn.textContent = originalText;
        if (result.success) {
            console.log('Success! Closing mini app in 500ms...');
            setTimeout(() => {
                console.log('Closing mini app now...');
                tg.close();
            }, 500);
        } else {
            showError(result.error || 'Failed to send data');
        }
    })
    .catch(error => {
        console.error('=== FETCH ERROR ===');
        console.error('Error type:', error.constructor.name);
        console.error('Error message:', error.message);
        console.error('Error stack:', error.stack);
        confirmBtn.disabled = false;
        confirmBtn.textContent = originalText;
        showError('Error: ' + error.message);
    });
}

// Event listeners
document.addEventListener('DOMContentLoaded', () => {
    console.log('=== DOMContentLoaded ===');
    // Initialize player when page loads
    initPlayer();
    
    // Button event listeners
    const setStartBtn = document.getElementById('set-start-btn');
    const setEndBtn = document.getElementById('set-end-btn');
    const resetBtn = document.getElementById('reset-btn');
    const confirmBtn = document.getElementById('confirm-btn');
    
    // Download mode toggle event listeners
    const modeVideo = document.getElementById('mode-video');
    const modeAudio = document.getElementById('mode-audio');
    
    if (modeVideo && modeAudio) {
        modeVideo.addEventListener('change', function() {
            if (this.checked) {
                audioOnly = false;
                updateTimestampDisplays();
            }
        });
        modeAudio.addEventListener('change', function() {
            if (this.checked) {
                audioOnly = true;
                updateTimestampDisplays();
            }
        });
    }
    
    if (setStartBtn) {
        setStartBtn.addEventListener('click', setStartTime);
        console.log('DEBUG: set-start-btn listener added');
    } else {
        console.error('ERROR: set-start-btn not found!');
    }
    
    if (setEndBtn) {
        setEndBtn.addEventListener('click', setEndTime);
        console.log('DEBUG: set-end-btn listener added');
    } else {
        console.error('ERROR: set-end-btn not found!');
    }
    
    if (resetBtn) {
        resetBtn.addEventListener('click', resetTimestamps);
        console.log('DEBUG: reset-btn listener added');
    } else {
        console.error('ERROR: reset-btn not found!');
    }
    
    if (confirmBtn) {
        console.log('DEBUG: Adding click listener to confirm-btn');
        confirmBtn.addEventListener('click', function(e) {
            console.log('=== CONFIRM BUTTON CLICKED ===');
            console.log('DEBUG: Event type:', e.type);
            console.log('DEBUG: Event target:', e.target);
            console.log('DEBUG: Button disabled?', confirmBtn.disabled);
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();
            console.log('DEBUG: About to call sendDataToBot()...');
            try {
                sendDataToBot();
                console.log('DEBUG: sendDataToBot() call completed');
            } catch (err) {
                console.error('ERROR calling sendDataToBot:', err);
                console.error('Error stack:', err.stack);
            }
            return false;
        });
        console.log('DEBUG: confirm-btn listener added');
    } else {
        console.error('ERROR: confirm-btn not found!');
    }
    
    // Initial timestamp display update
    updateTimestampDisplays();
    
    // Test fetch connectivity
    console.log('DEBUG: Testing fetch connectivity...');
    fetch(window.location.origin + '/api/mini_app/test')
        .then(r => r.json())
        .then(data => console.log('DEBUG: Connectivity test SUCCESS:', data))
        .catch(err => console.error('DEBUG: Connectivity test FAILED:', err));
});

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    if (currentTimeUpdateInterval) {
        clearInterval(currentTimeUpdateInterval);
    }
    if (playerWrapper && playerWrapper.cleanup) {
        playerWrapper.cleanup();
    }
});

