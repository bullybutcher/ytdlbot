// Standalone YouTube Player API - adapted from Observable notebook
// https://observablehq.com/@radames/youtube-player-api

/**
 * Load YouTube IFrame API
 * @returns {Promise<Object>} YT object
 */
function loadYouTubeAPI() {
    return new Promise((resolve, reject) => {
        // Check if already loaded
        if (window.YT && window.YT.Player) {
            resolve(window.YT);
            return;
        }

        // Check if script is already loading
        if (window.YTLoading) {
            window.YTLoading.then(resolve).catch(reject);
            return;
        }

        // Create loading promise
        window.YTLoading = new Promise((resolveLoading, rejectLoading) => {
            // Create script tag
            const tag = document.createElement('script');
            tag.src = 'https://www.youtube.com/iframe_api';
            const firstScriptTag = document.getElementsByTagName('script')[0];
            firstScriptTag.parentNode.insertBefore(tag, firstScriptTag);

            // Set up callback
            window.onYouTubeIframeAPIReady = () => {
                resolveLoading(window.YT);
            };

            // Handle errors
            tag.onerror = () => {
                rejectLoading(new Error('Failed to load YouTube IFrame API'));
            };

            // Timeout after 10 seconds
            setTimeout(() => {
                if (!window.YT) {
                    rejectLoading(new Error('YouTube IFrame API loading timeout'));
                }
            }, 10000);
        });

        window.YTLoading.then(resolve).catch(reject);
    });
}

/**
 * Get player state name from value
 * @param {number} value - Player state code
 * @param {Object} YT - YouTube API object
 * @returns {string} State name
 */
function getPlayerStateName(value, YT) {
    return Object.keys(YT.PlayerState).find(key => YT.PlayerState[key] === value) || 'UNKNOWN';
}

/**
 * Create YouTube player instance
 * @param {string} videoId - YouTube video ID
 * @param {number|null} startSeconds - Start time in seconds
 * @param {number|null} endSeconds - End time in seconds
 * @param {string|null} ccLang - Caption language preference
 * @returns {Promise<Object>} Player container object
 */
async function createYouTubePlayer(videoId, startSeconds = null, endSeconds = null, ccLang = null) {
    const YT = await loadYouTubeAPI();

    const container = document.createElement('div');
    const playerElement = document.createElement('div');
    container.classList.add('embed-container');
    container.appendChild(playerElement);

    // Add styles
    const style = document.createElement('style');
    style.textContent = `
        .embed-container {
            position: relative;
            padding-bottom: 56.25%;
            height: 0;
            overflow: hidden;
            max-width: 100%;
        }
        .embed-container iframe,
        .embed-container object,
        .embed-container embed {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
        }
    `;
    document.head.appendChild(style);

    let playerInstance = null;
    let currentTime = 0;
    let duration = 0;

    const playerPromise = new Promise((resolve, reject) => {
        try {
            playerInstance = new YT.Player(playerElement, {
                playerVars: {
                    autoplay: 0,
                    controls: 1,
                    cc_load_policy: ccLang ? 1 : 0,
                    cc_lang_pref: ccLang || undefined,
                    enablejsapi: 1,
                    origin: window.location.origin
                },
                events: {
                    onReady: (event) => {
                        // Load video with start/end times
                        if (startSeconds !== null || endSeconds !== null) {
                            event.target.cueVideoById({
                                videoId: videoId,
                                startSeconds: startSeconds || 0,
                                endSeconds: endSeconds || undefined
                            });
                        } else {
                            event.target.cueVideoById({ videoId: videoId });
                        }
                        
                        // Get duration
                        duration = event.target.getDuration();
                        resolve(event.target);
                    },
                    onStateChange: (event) => {
                        // Update current time periodically
                        updateCurrentTime();
                        // Track playback state (1 = playing, 2 = paused)
                        if (window.updateVideoPlaybackState) {
                            window.updateVideoPlaybackState(event.data === 1);
                        }
                    },
                    onError: (event) => {
                        reject(new Error(`YouTube player error: ${event.data}`));
                    }
                }
            });
        } catch (error) {
            reject(error);
        }
    });

    // Function to update current time
    function updateCurrentTime() {
        if (playerInstance && playerInstance.getCurrentTime) {
            try {
                currentTime = playerInstance.getCurrentTime();
            } catch (e) {
                // Player might not be ready
            }
        }
    }

    // Update current time every 100ms
    const timeUpdateInterval = setInterval(updateCurrentTime, 100);

    // Return player container object
    return {
        container: container,
        player: playerPromise,
        videoId: videoId,
        getCurrentTime: () => {
            if (playerInstance && playerInstance.getCurrentTime) {
                try {
                    return playerInstance.getCurrentTime();
                } catch (e) {
                    return currentTime;
                }
            }
            return currentTime;
        },
        getDuration: async () => {
            const player = await playerPromise;
            try {
                return player.getDuration();
            } catch (e) {
                return duration;
            }
        },
        seekTo: async (seconds, allowSeekAhead = true) => {
            const player = await playerPromise;
            player.seekTo(seconds, allowSeekAhead);
        },
        playVideo: async () => {
            const player = await playerPromise;
            player.playVideo();
        },
        pauseVideo: async () => {
            const player = await playerPromise;
            player.pauseVideo();
        },
        cleanup: () => {
            clearInterval(timeUpdateInterval);
            if (playerInstance && playerInstance.destroy) {
                try {
                    playerInstance.destroy();
                } catch (e) {
                    // Ignore cleanup errors
                }
            }
        }
    };
}

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { createYouTubePlayer, loadYouTubeAPI };
}

