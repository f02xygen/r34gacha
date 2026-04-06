document.addEventListener("DOMContentLoaded", () => {
    const tg = window.Telegram.WebApp;
    tg.ready();
    tg.expand();


    // UI Elements
    const lever = document.getElementById("lever");
    const drum = document.getElementById("drum");
    const drumItemC = document.getElementById("drum-item-current");
    const charName = document.getElementById("char-name");
    const valRank = document.getElementById("val-rank");
    const valArts = document.getElementById("val-arts");
    const valStatus = document.getElementById("val-status");
    const statusContainer = document.getElementById("status-container");
    const btnFavorite = document.getElementById("btn-favorite");
    const statusLed = document.getElementById("status-led");
    const errorScreen = document.getElementById("error-screen");
    const errorText = document.getElementById("error-text");

    let isRolling = false;
    let currentCharacterId = null;
    let isFavorite = false;
    let cooldownTimer = null;
    let cooldownRemaining = 0;

    // Initial setup
    statusLed.classList.add("ready");

    function startCooldown(seconds) {
        if (cooldownTimer) clearInterval(cooldownTimer);
        cooldownRemaining = Math.ceil(seconds);
        valStatus.classList.add("text-red");
        
        function updateDisplay() {
            if (cooldownRemaining <= 0) {
                clearInterval(cooldownTimer);
                valStatus.classList.remove("text-red");
                valStatus.innerText = "RDY";
                cooldownRemaining = 0;
                statusContainer.classList.remove("flash");
            } else {
                valStatus.innerText = cooldownRemaining.toString().padStart(2, '0') + "s";
            }
        }
        
        updateDisplay();
        cooldownTimer = setInterval(() => {
            cooldownRemaining--;
            updateDisplay();
        }, 1000);
    }

    function showError(msg) {
        errorText.innerText = msg;
        errorScreen.classList.remove("hidden");
        setTimeout(() => errorScreen.classList.add("hidden"), 3000);
    }

    function updateCharacterName(name) {
        // Reset marquee
        charName.classList.remove("marquee-active");
        charName.innerText = name;
        charName.setAttribute("data-text", name);
        
        // Wait for DOM layout to check for overflow
        requestAnimationFrame(() => {
            const wrapper = charName.parentElement;
            // Clear any potential duplication from previous name
            charName.innerText = name;
            
            if (charName.scrollWidth > wrapper.offsetWidth) {
                // Duplicate text with a gap for seamless looping
                const gap = "\u00A0\u00A0\u00A0\u00A0\u00A0"; // 5 non-breaking spaces
                charName.innerText = name + gap + name + gap;
                charName.classList.add("marquee-active");
            }
        });
    }

    // Slider interaction (Horizontal Drag)
    let startX = 0;
    let currentX = 0;
    let isDragging = false;
    let lastTickProgress = 0;
    let maxSliderPx = 0;

    // Calculate max slide distance
    function calculateMaxSlide() {
        const container = document.querySelector('.slider-container');
        const handle = document.getElementById('lever');
        if (container && handle) {
            maxSliderPx = container.offsetWidth - handle.offsetWidth - 4; // 2px edge gap padding
        }
    }
    
    // Call it initially and on resize
    setTimeout(calculateMaxSlide, 100);
    window.addEventListener('resize', calculateMaxSlide);

    function updateLeverTransform(x) {
        lever.style.transform = `translateX(${x}px)`;
    }

    function doTickHaptic() {
        if (tg.platform === 'android' && navigator.vibrate) {
            navigator.vibrate(5);
        } else if (tg.HapticFeedback) {
            tg.HapticFeedback.impactOccurred("rigid");
        }
    }

    function doMediumHaptic() {
        if (tg.platform === 'android' && navigator.vibrate) {
            navigator.vibrate([10, 30, 10]);
        } else if (tg.HapticFeedback) {
            tg.HapticFeedback.impactOccurred("medium");
        }
    }

    function doHeavyHaptic() {
        if (tg.platform === 'android' && navigator.vibrate) {
            navigator.vibrate([15, 20, 20]);
        } else if (tg.HapticFeedback) {
            tg.HapticFeedback.impactOccurred("heavy");
        }
    }

    function doErrorHaptic() {
        if (tg.platform === 'android' && navigator.vibrate) {
            navigator.vibrate([20, 50, 20, 50, 20]);
        } else if (tg.HapticFeedback) {
            tg.HapticFeedback.notificationOccurred("error");
        }
    }

    function handleDragStart(pageX) {
        if (isRolling) return;
        isDragging = true;
        startX = pageX;
        currentX = pageX;
        lastTickProgress = 0;
        lever.style.transition = 'none'; // Follow raw drag
        calculateMaxSlide();
    }

    function handleDragMove(pageX) {
        if (!isDragging) return;
        currentX = pageX;
        let dx = currentX - startX;
        if (dx < 0) dx = 0; // Prevent breaking left bounds
        if (dx > maxSliderPx) dx = maxSliderPx; // Maximum right bound
        
        updateLeverTransform(dx);
        
        let progress = dx / maxSliderPx;
        let pullSteps = Math.floor(progress * 8); // 8 ticks across the bar
        if (pullSteps !== lastTickProgress) {
            lastTickProgress = pullSteps;
            doTickHaptic();
        }
    }

    function handleDragEnd() {
        if (!isDragging) return;
        isDragging = false;
        
        let dx = currentX - startX;
        let progress = dx / maxSliderPx;
        
        // Always snap back on release
        lever.style.transition = 'transform 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.1)';
        updateLeverTransform(0);
        
        if (progress >= 0.9) { // Needs to be pulled 90% of the way
            if (cooldownRemaining > 0) {
                // Cooldown fail upon full release
                statusContainer.classList.remove("flash");
                void statusContainer.offsetWidth; // trigger reflow
                statusContainer.classList.add("flash");
                doErrorHaptic();
            } else {
                // Success! Trigger Roll
                doHeavyHaptic();
                triggerRoll();
            }
        }
    }

    // Touch Support
    lever.addEventListener("touchstart", (e) => handleDragStart(e.touches[0].clientX));
    window.addEventListener("touchmove", (e) => handleDragMove(e.touches[0].clientX));
    window.addEventListener("touchend", () => handleDragEnd());
    window.addEventListener("touchcancel", () => handleDragEnd());

    // Mouse Support for Desktop
    lever.addEventListener("mousedown", (e) => handleDragStart(e.clientX));
    window.addEventListener("mousemove", (e) => {
        if (isDragging) {
            e.preventDefault();
            handleDragMove(e.clientX);
        }
    });
    window.addEventListener("mouseup", () => handleDragEnd());

    async function triggerRoll() {
        if (isRolling) return;

        // UI Updates for rolling state
        isRolling = true;
        statusLed.classList.remove("ready");
        statusLed.classList.add("busy");
        btnFavorite.disabled = true;
        btnFavorite.classList.remove("active");

        updateCharacterName("ROLLING...");
        charName.classList.add("animating");

        valRank.innerText = "-";
        valArts.innerText = "-";

        // Start drum animation (fake spinning)
        drumItemC.classList.remove("text-glitch", "animating");
        let spinInterval = setInterval(() => {
            const colors = ['#f00', '#0f0', '#00f', '#ff0', '#0ff', '#f0f'];
            drumItemC.style.backgroundColor = colors[Math.floor(Math.random() * colors.length)];
            drumItemC.innerText = "?";
            drumItemC.style.backgroundImage = 'none';
        }, 100);
        drum.classList.add("spinning");

        try {
            const res = await fetch("/api/roll", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": tg.initData || ""
                }
            });

            const data = await res.json();

            if (!res.ok) {
                let e = new Error(data.error || "Unknown error occurred");
                e.data = data;
                throw e;
            }

            // Finish animation with a slight delay for suspense
            setTimeout(() => {
                finishRoll(data, spinInterval);
            }, 800);

        } catch (err) {
            clearInterval(spinInterval);
            drum.classList.remove("spinning");
            drumItemC.style.backgroundColor = "#0b0c10";
            drumItemC.innerText = "ERROR";
            drumItemC.setAttribute("data-text", "ERROR");
            drumItemC.classList.add("text-glitch", "animating");
            
            if (err.data && err.data.cooldown) {
                startCooldown(err.data.cooldown);
                statusContainer.classList.add("flash");
            } else {
                showError(err.message);
            }
            
            resetLever();
        }
    }

    function finishRoll(data, spinInterval) {
        clearInterval(spinInterval);
        drum.classList.remove("spinning");

        // Haptic feedback was removed from network load to happen instantly on drag execution

        // Update states
        currentCharacterId = data.character_id;
        isFavorite = data.is_favorite;

        // Update display screens
        valRank.innerText = data.rank;
        valArts.innerText = data.post_count;

        updateCharacterName(data.tag_name);
        charName.classList.remove("animating");

        // Update image
        drumItemC.innerText = "";
        drumItemC.style.backgroundColor = "#000";
        drumItemC.classList.remove("text-glitch", "animating");
        if (data.image_url) {
            drumItemC.style.backgroundImage = `url('${data.image_url}')`;
            drumItemC.style.backgroundSize = "contain";
            drumItemC.style.backgroundRepeat = "no-repeat";
        } else {
            drumItemC.innerText = "NO IMAGE";
            drumItemC.setAttribute("data-text", "NO IMAGE");
            drumItemC.classList.add("text-glitch", "animating");
        }

        // Update favorite button
        btnFavorite.disabled = false;
        if (isFavorite) {
            btnFavorite.classList.add("active");
        } else {
            btnFavorite.classList.remove("active");
        }

        // Restore controls
        resetLever();
        
        // Start local cooldown assumption matching server Action Cooldown (10s)
        startCooldown(10);
    }

    function resetLever() {
        setTimeout(() => {
            statusLed.classList.remove("busy");
            statusLed.classList.add("ready");
            isRolling = false;
        }, 100);
    }

    // Favorite Button listener
    btnFavorite.addEventListener("click", async () => {
        if (!currentCharacterId || btnFavorite.disabled) return;

        doMediumHaptic();
        btnFavorite.disabled = true;

        try {
            const res = await fetch("/api/favorite", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": tg.initData || ""
                },
                body: JSON.stringify({ character_id: currentCharacterId })
            });
            const data = await res.json();

            if (res.ok) {
                isFavorite = data.is_favorite;
                if (isFavorite) {
                    btnFavorite.classList.add("active");
                } else {
                    btnFavorite.classList.remove("active");
                }
            } else {
                showError(data.error);
            }
        } catch (e) {
            showError("Network error");
        } finally {
            btnFavorite.disabled = false;
        }
    });

});
