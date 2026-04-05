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
    const btnFavorite = document.getElementById("btn-favorite");
    const statusLed = document.getElementById("status-led");
    const errorScreen = document.getElementById("error-screen");
    const errorText = document.getElementById("error-text");

    let isRolling = false;
    let currentCharacterId = null;
    let isFavorite = false;

    // Initial setup
    statusLed.classList.add("ready");

    function showError(msg) {
        errorText.innerText = msg;
        errorScreen.classList.remove("hidden");
        setTimeout(() => errorScreen.classList.add("hidden"), 3000);
    }

    // Lever interaction (click / touch)
    lever.addEventListener("click", pullLever);

    // Allow touch dragging on lever for a more tactile feel
    let touchStartY = 0;
    lever.addEventListener("touchstart", (e) => {
        touchStartY = e.touches[0].clientY;
    });
    lever.addEventListener("touchmove", (e) => {
        if (isRolling) return;
        const currentY = e.touches[0].clientY;
        if (currentY - touchStartY > 30) {
            pullLever();
        }
    });

    async function pullLever() {
        if (isRolling) return;

        // Haptic feedback
        if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred("heavy");

        // UI Updates for rolling state
        isRolling = true;
        lever.classList.add("pulled");
        statusLed.classList.remove("ready");
        statusLed.classList.add("busy");
        btnFavorite.disabled = true;
        btnFavorite.classList.remove("active");

        charName.innerText = "ROLLING...";
        charName.setAttribute("data-text", "ROLLING...");
        charName.classList.add("animating");

        valRank.innerText = "-";
        valArts.innerText = "-";

        // Start drum animation (fake spinning)
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
                throw new Error(data.error || "Unknown error occurred");
            }

            // Finish animation with a slight delay for suspense
            setTimeout(() => {
                finishRoll(data, spinInterval);
            }, 800);

        } catch (err) {
            clearInterval(spinInterval);
            drum.classList.remove("spinning");
            drumItemC.style.backgroundColor = "#1a1a1a";
            drumItemC.innerText = "ERROR";
            showError(err.message);
            resetLever();
        }
    }

    function finishRoll(data, spinInterval) {
        clearInterval(spinInterval);
        drum.classList.remove("spinning");

        if (tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");

        // Update states
        currentCharacterId = data.character_id;
        isFavorite = data.is_favorite;

        // Update display screens
        valRank.innerText = data.rank;
        valArts.innerText = data.post_count;

        charName.innerText = data.tag_name;
        charName.setAttribute("data-text", data.tag_name);
        charName.classList.remove("animating");

        // Update image
        drumItemC.innerText = "";
        drumItemC.style.backgroundColor = "#000";
        if (data.image_url) {
            drumItemC.style.backgroundImage = `url('${data.image_url}')`;
            drumItemC.style.backgroundSize = "contain";
            drumItemC.style.backgroundRepeat = "no-repeat";
        } else {
            drumItemC.innerText = "NO IMAGE";
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
    }

    function resetLever() {
        setTimeout(() => {
            lever.classList.remove("pulled");
            statusLed.classList.remove("busy");
            statusLed.classList.add("ready");
            isRolling = false;
        }, 300);
    }

    // Favorite Button listener
    btnFavorite.addEventListener("click", async () => {
        if (!currentCharacterId || btnFavorite.disabled) return;

        if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred("light");
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
