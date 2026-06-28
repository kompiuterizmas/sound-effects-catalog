const searchInput = document.getElementById("searchInput");
const catalogList = document.getElementById("catalogList");
let rows = Array.from(catalogList.querySelectorAll(".audio-row"));

const durationFilter = document.getElementById("durationFilter");
const startFilter = document.getElementById("startFilter");
const shapeFilter = document.getElementById("shapeFilter");
const energyFilter = document.getElementById("energyFilter");
const endingFilter = document.getElementById("endingFilter");

const filterInputs = [
    durationFilter,
    startFilter,
    shapeFilter,
    energyFilter,
    endingFilter
];

const audioPlayers = Array.from(document.querySelectorAll("audio"));

let searchTimeout = null;

const audioIndex = createAudioIndex();
let searchableRows = createSearchableRows();
updateVisibleCount();
initializeFavorites();
function updateVisibleCount() {
    const visibleCountElement = document.getElementById("visibleCount");

    if (!visibleCountElement) {
        return;
    }

    const visibleCount = rows.filter(row => row.style.display !== "none").length;
    visibleCountElement.textContent = visibleCount;
}

function resetFilters() {
    searchInput.value = "";

    filterInputs.forEach(filterInput => {
        filterInput.value = "";
    });

    clearSimilarClassesOnly();

    rows.forEach(row => {
        row.style.display = "";
    });

    document.getElementById("clearSimilarButton").style.display = "none";

    updateVisibleCount();
    showStatusMessage("Filters reset.");
}

function createAudioIndex() {
    return rows.map(row => {
        let features = {};

        try {
            features = JSON.parse(row.dataset.audioFeatures || "{}");
        } catch (error) {
            features = {};
        }

        return {
            row: row,
            envelope: Array.isArray(features.envelope) ? features.envelope : [],
            spectrum: Array.isArray(features.spectrum) ? features.spectrum : [],
            onsets: Array.isArray(features.onsets) ? features.onsets : []
        };
    });
}

function createSearchableRows() {
    return rows.map(row => {
        const searchableText = [
            row.dataset.name || "",
            row.dataset.folder || "",
            row.dataset.fullPath || "",
            row.dataset.type || ""
        ].join(" ").toLowerCase();

        return {
            row: row,
            text: searchableText
        };
    });
}

function getAudioIndexItem(row) {
    return audioIndex.find(item => item.row === row) || null;
}

function showStatusMessage(message, isError = false) {
    const statusMessage = document.getElementById("statusMessage");

    if (statusMessage.hideTimeout) {
        clearTimeout(statusMessage.hideTimeout);
    }

    if (statusMessage.fadeTimeout) {
        clearTimeout(statusMessage.fadeTimeout);
    }

    statusMessage.textContent = message;
    statusMessage.classList.toggle("error", isError);
    statusMessage.style.display = "block";

    requestAnimationFrame(() => {
        statusMessage.classList.add("visible");
    });

    statusMessage.hideTimeout = setTimeout(() => {
        statusMessage.classList.remove("visible");

        statusMessage.fadeTimeout = setTimeout(() => {
            statusMessage.style.display = "none";
        }, 220);
    }, 2500);
}

function showLoading(message) {
    const loadingText = document.getElementById("loadingText");

    if (loadingText) {
        loadingText.textContent = message;
    }

    document.body.classList.add("app-loading");
}


function hideLoading() {
    document.body.classList.remove("app-loading");
}

function applyTextAndFilterSearch() {
    const query = searchInput.value.trim().toLowerCase();

    const selectedDuration = durationFilter.value;
    const selectedStart = startFilter.value;
    const selectedShape = shapeFilter.value;
    const selectedEnergy = energyFilter.value;
    const selectedEnding = endingFilter.value;

    clearSimilarClassesOnly();

    document.getElementById("clearSimilarButton").style.display = "none";

    searchableRows.forEach(item => {
        const row = item.row;

        const textMatches = item.text.includes(query);

        const durationMatches = !selectedDuration || row.dataset.durationClass === selectedDuration;
        const startMatches = !selectedStart || row.dataset.startClass === selectedStart;
        const shapeMatches = !selectedShape || row.dataset.shapeClass === selectedShape;
        const energyMatches = !selectedEnergy || row.dataset.energyClass === selectedEnergy;
        const endingMatches = !selectedEnding || row.dataset.endingClass === selectedEnding;

        row.style.display = (
            textMatches &&
            durationMatches &&
            startMatches &&
            shapeMatches &&
            energyMatches &&
            endingMatches
        ) ? "" : "none";
    });
    updateVisibleCount();
}

searchInput.addEventListener("input", function() {
    if (searchTimeout) {
        clearTimeout(searchTimeout);
    }

    searchTimeout = setTimeout(() => {
        applyTextAndFilterSearch();
    }, 120);
});

filterInputs.forEach(filterInput => {
    filterInput.addEventListener("change", applyTextAndFilterSearch);
});

audioPlayers.forEach(audio => {
    audio.addEventListener("play", () => {
        rows.forEach(row => {
            row.classList.remove("currently-playing");
        });

        audioPlayers.forEach(otherAudio => {
            if (otherAudio !== audio) {
                otherAudio.pause();
                otherAudio.currentTime = 0;
            }
        });

        const currentRow = audio.closest(".audio-row");

        if (currentRow) {
            currentRow.classList.add("currently-playing");
        }
    });
});

function clearSimilarClassesOnly() {
    const oldDivider = catalogList.querySelector(".similar-divider");

    if (oldDivider) {
        oldDivider.remove();
    }

    rows.forEach(row => {
        row.classList.remove("similar-selected");
        row.classList.remove("similar-match");
    });
}

function clearSimilarSearch() {
    clearSimilarClassesOnly();

    rows.forEach(row => {
        row.style.display = "";
    });

    document.getElementById("clearSimilarButton").style.display = "none";
    updateVisibleCount();
    showStatusMessage("Similar search cleared.");
}

function calculateVectorSimilarity(vectorA, vectorB) {
    if (!vectorA.length || !vectorB.length || vectorA.length !== vectorB.length) {
        return 0;
    }

    let distance = 0;
    let maxDistance = 0;

    for (let index = 0; index < vectorA.length; index++) {
        const valueA = parseFloat(vectorA[index] || 0);
        const valueB = parseFloat(vectorB[index] || 0);
        const difference = valueA - valueB;

        distance += difference * difference;
        maxDistance += 1;
    }

    distance = Math.sqrt(distance);
    maxDistance = Math.sqrt(maxDistance);

    if (maxDistance === 0) {
        return 0;
    }

    return Math.max(0, 1 - distance / maxDistance);
}

function getBeginningVector(envelope, ratio = 0.25) {
    if (!envelope.length) {
        return [];
    }

    const count = Math.max(8, Math.floor(envelope.length * ratio));
    return envelope.slice(0, count);
}

function scrollToRowWithTopBarOffset(row) {
    const topBar = document.querySelector(".top-bar");
    const topBarHeight = topBar ? topBar.offsetHeight : 0;
    const extraGap = 12;

    const rowTop = row.getBoundingClientRect().top + window.scrollY;
    const targetScrollTop = rowTop - topBarHeight - extraGap;

    window.scrollTo({
        top: Math.max(0, targetScrollTop),
        behavior: "smooth"
    });
}

function findSimilarFromWaveform(button) {
    const selectedRow = button.closest(".audio-row");

    if (!selectedRow) {
        showStatusMessage("Selected row was not found.", true);
        return;
    }

    const selectedItem = getAudioIndexItem(selectedRow);

    if (!selectedItem || !selectedItem.envelope.length) {
        showStatusMessage("Waveform data is not available for this file.", true);
        return;
    }

    showLoading("Searching similar sounds...");

    setTimeout(() => {
        try {
            const maxResults = 30;

            const matches = audioIndex
                .filter(item => {
                    if (!item.envelope.length) {
                        return false;
                    }

                    if (item.row === selectedRow) {
                        return true;
                    }

                    const row = item.row;

                    const sameDuration =
                        selectedRow.dataset.durationClass === row.dataset.durationClass;

                    const sameStart =
                        selectedRow.dataset.startClass === row.dataset.startClass;

                    const sameShape =
                        selectedRow.dataset.shapeClass === row.dataset.shapeClass;

                    const samePeak =
                        selectedRow.dataset.peakPositionClass === row.dataset.peakPositionClass;

                    return sameDuration || sameStart || sameShape || samePeak;
                })
                .map(item => {
                    const row = item.row;

                    const waveformSimilarity = calculateVectorSimilarity(
                        selectedItem.envelope,
                        item.envelope
                    );

                    const beginningSimilarity = calculateVectorSimilarity(
                        getBeginningVector(selectedItem.envelope, 0.25),
                        getBeginningVector(item.envelope, 0.25)
                    );

                    const durationBonus =
                        selectedRow.dataset.durationClass === row.dataset.durationClass ? 1 : 0;

                    const peakBonus =
                        selectedRow.dataset.peakPositionClass === row.dataset.peakPositionClass ? 1 : 0;

                    const shapeBonus =
                        selectedRow.dataset.shapeClass === row.dataset.shapeClass ? 1 : 0;

                    const finalScore =
                        waveformSimilarity * 0.60 +
                        beginningSimilarity * 0.15 +
                        durationBonus * 0.10 +
                        peakBonus * 0.10 +
                        shapeBonus * 0.05;

                    return {
                        row: row,
                        similarity: finalScore
                    };
                })
                .sort((a, b) => b.similarity - a.similarity)
                .slice(0, maxResults);

            showSimilarResults(
                selectedRow,
                matches,
                `Similar files shown: ${Math.max(0, matches.length - 1)}`,
                "No similar files found."
            );
        } finally {
            hideLoading();
        }
    }, 30);
}

function findSameBeginningFromWaveform(button) {
    const selectedRow = button.closest(".audio-row");

    if (!selectedRow) {
        showStatusMessage("Selected row was not found.", true);
        return;
    }

    const selectedItem = getAudioIndexItem(selectedRow);

    if (!selectedItem || !selectedItem.envelope.length) {
        showStatusMessage("Waveform data is not available for this file.", true);
        return;
    }

    showLoading("Searching similar sounds...");

    setTimeout(() => {
        try {
            const selectedBeginning = getBeginningVector(selectedItem.envelope, 0.25);
            const minSimilarity = 0.965;
            const maxResults = 30;

            const matches = audioIndex
                .filter(item => item.envelope.length)
                .map(item => {
                    return {
                        row: item.row,
                        similarity: calculateVectorSimilarity(
                            selectedBeginning,
                            getBeginningVector(item.envelope, 0.25)
                        )
                    };
                })
                .filter(item => item.row === selectedRow || item.similarity >= minSimilarity)
                .sort((a, b) => b.similarity - a.similarity)
                .slice(0, maxResults);

            showSimilarResults(
                selectedRow,
                matches,
                `Same beginning found: ${Math.max(0, matches.length - 1)}`,
                "No matching beginning found."
            );
        } finally {
            hideLoading();
        }
    }, 30);
}

function showSimilarResults(selectedRow, matches, successMessage, emptyMessage) {
    clearSimilarClassesOnly();
    rows.forEach(row => {
        const oldBadge = row.querySelector(".similarity-badge");

        if (oldBadge) {
            oldBadge.remove();
        }
    });

    searchInput.value = "";
    filterInputs.forEach(filterInput => {
        filterInput.value = "";
    });

    const matchingRows = matches.map(item => item.row);

    if (!matchingRows.includes(selectedRow)) {
        matchingRows.unshift(selectedRow);
    }

    const fragment = document.createDocumentFragment();

    matches.forEach(item => {
        const row = item.row;
        row.style.display = "";

        if (row === selectedRow) {
            row.classList.add("similar-selected");
        } else {
            row.classList.add("similar-match");
            addSimilarityBadge(row, item.similarity);
        }

        fragment.appendChild(row);
    });

    const divider = document.createElement("div");
    divider.className = "similar-divider";
    divider.textContent = successMessage;
    fragment.appendChild(divider);

    rows.forEach(row => {
        if (!matchingRows.includes(row)) {
            row.style.display = "none";
            fragment.appendChild(row);
        }
    });

    catalogList.appendChild(fragment);
    document.getElementById("clearSimilarButton").style.display = "inline-block";
    updateVisibleCount();

    scrollToRowWithTopBarOffset(selectedRow);

    if (matchingRows.length <= 1) {
        showStatusMessage(emptyMessage);
    } else {
        showStatusMessage(successMessage);
    }
}
function addSimilarityBadge(row, similarity) {
    const waveformArea = row.querySelector(".waveform-area");

    if (!waveformArea) {
        return;
    }

    const oldBadge = waveformArea.querySelector(".similarity-badge");

    if (oldBadge) {
        oldBadge.remove();
    }

    const badge = document.createElement("span");
    badge.className = "similarity-badge";
    badge.textContent = `${Math.round(similarity * 100)}% similar`;

    waveformArea.appendChild(badge);
}

function renameFile(button) {
    const row = button.closest(".audio-row");
    const input = row.querySelector(".rename-input");

    const oldPath = row.dataset.fullPath || "";
    const newName = input.value.trim();

    if (!newName) {
        showStatusMessage("File name cannot be empty.", true);
        return;
    }

    fetch("/rename", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            old_path: oldPath,
            new_name: newName
        })
    })
        .then(response => response.json())
        .then(result => {
            if (!result.success) {
                showStatusMessage(result.message || "Rename failed.", true);
                return;
            }

            row.dataset.fullPath = result.new_path;
            row.dataset.name = result.new_name;
            row.dataset.type = result.new_type;

            input.value = result.new_stem;
            input.title = result.new_stem;

            const formatBadge = row.querySelector(".format-badge");
            if (formatBadge) {
                formatBadge.textContent = result.new_type;
            }

            const openFolderButton = row.querySelector(".open-folder-button");
            if (openFolderButton) {
                openFolderButton.title = result.new_path;
                openFolderButton.setAttribute("aria-label", result.new_path);
            }

            const audioSource = row.querySelector("audio source");
            const audio = row.querySelector("audio");

            if (audioSource && result.audio_path) {
                audioSource.src = result.audio_path;

                if (audio) {
                    audio.load();
                }
            }

            const waveformImage = row.querySelector(".waveform");

            if (waveformImage && result.waveform_path) {
                waveformImage.src = result.waveform_path;
            }

            searchableRows = createSearchableRows();

            showStatusMessage("File renamed.");
        })
        .catch(error => {
            showStatusMessage(`Rename failed: ${error}`, true);
        });
}

function openFolder(button) {
    const row = button.closest(".audio-row");

    fetch("/open-folder", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            path: row.dataset.fullPath || ""
        })
    })
        .then(response => response.json())
        .then(result => {
            showStatusMessage(result.message || "Done.", !result.success);
        })
        .catch(error => {
            showStatusMessage(`Could not open folder: ${error}`, true);
        });
}

function deleteFile(button) {
    const row = button.closest(".audio-row");
    const fileName = row.dataset.name || "this file";

    if (!confirm(`Move "${fileName}" to deleted files?`)) {
        return;
    }

    fetch("/delete-file", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            path: row.dataset.fullPath || ""
        })
    })
        .then(response => response.json())
        .then(result => {
            if (!result.success) {
                showStatusMessage(result.message || "Delete failed.", true);
                return;
            }

            row.remove();
            rows = rows.filter(item => item !== row);
            searchableRows = createSearchableRows();

            showStatusMessage(result.message || "File moved to deleted files.");
        })
        .catch(error => {
            showStatusMessage(`Delete failed: ${error}`, true);
        });
}

function cleanGeneratedFiles() {
    fetch("/clean-generated", {
        method: "POST"
    })
        .then(response => response.json())
        .then(result => {
            showStatusMessage(result.message || "Done.", !result.success);
        })
        .catch(error => {
            showStatusMessage(`Clean failed: ${error}`, true);
        });
}
function getFavoriteKey(row) {
    return `favorite:${row.dataset.fullPath || ""}`;
}


function isFavorite(row) {
    return localStorage.getItem(getFavoriteKey(row)) === "1";
}


function updateFavoriteButton(row) {
    const button = row.querySelector(".favorite-button");

    if (!button) {
        return;
    }

    if (isFavorite(row)) {
        button.textContent = "★ Favorite";
        row.classList.add("favorite-row");
    } else {
        button.textContent = "☆ Favorite";
        row.classList.remove("favorite-row");
    }
}


function initializeFavorites() {
    rows.forEach(row => {
        updateFavoriteButton(row);
    });
}


function toggleFavorite(button) {
    const row = button.closest(".audio-row");

    if (!row) {
        return;
    }

    if (isFavorite(row)) {
        localStorage.removeItem(getFavoriteKey(row));
    } else {
        localStorage.setItem(getFavoriteKey(row), "1");
    }

    updateFavoriteButton(row);
}


function showOnlyFavorites() {
    clearSimilarClassesOnly();

    searchInput.value = "";

    filterInputs.forEach(filterInput => {
        filterInput.value = "";
    });

    rows.forEach(row => {
        row.style.display = isFavorite(row) ? "" : "none";
    });

    document.getElementById("clearSimilarButton").style.display = "none";

    updateVisibleCount();
    showStatusMessage("Showing favorites.");
}
window.findSameBeginningFromWaveform = findSameBeginningFromWaveform;
window.findSimilarFromWaveform = findSimilarFromWaveform;
window.clearSimilarSearch = clearSimilarSearch;
window.resetFilters = resetFilters;
window.cleanGeneratedFiles = cleanGeneratedFiles;
window.renameFile = renameFile;
window.openFolder = openFolder;
window.deleteFile = deleteFile;
window.toggleFavorite = toggleFavorite;
window.showOnlyFavorites = showOnlyFavorites;

document.body.classList.remove("app-loading");