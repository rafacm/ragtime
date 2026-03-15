(function() {
    'use strict';

    function init(config) {
        var debounceMs = config.debounceMs || 300;
        var minChars = config.minChars || 3;

        var wrapper = document.querySelector('.wikidata-search-wrapper');
        var searchInput = document.getElementById('wikidata-search-input');
        var resultsContainer = document.getElementById('wikidata-results');
        var selectedContainer = document.getElementById('wikidata-selected');

        if (!searchInput || !resultsContainer || !wrapper) return;

        // Read URLs from data attributes (set by Django template)
        var searchUrl = wrapper.getAttribute('data-search-url') || '/episodes/wikidata/search/';
        var detailUrlTemplate = wrapper.getAttribute('data-detail-url') || '/episodes/wikidata/entity/__QID__/';

        var debounceTimer = null;

        searchInput.addEventListener('input', function() {
            var query = this.value.trim();
            clearTimeout(debounceTimer);

            if (query.length < minChars) {
                resultsContainer.innerHTML = '';
                resultsContainer.style.display = 'none';
                return;
            }

            debounceTimer = setTimeout(function() {
                performSearch(query, searchUrl, resultsContainer, selectedContainer, detailUrlTemplate);
            }, debounceMs);
        });

        // Close results on outside click
        document.addEventListener('click', function(e) {
            if (!searchInput.contains(e.target) && !resultsContainer.contains(e.target)) {
                resultsContainer.style.display = 'none';
            }
        });
    }

    function performSearch(query, searchUrl, resultsContainer, selectedContainer, detailUrlTemplate) {
        fetch(searchUrl + '?q=' + encodeURIComponent(query))
            .then(function(response) { return response.json(); })
            .then(function(data) {
                renderResults(data.results || [], resultsContainer, selectedContainer, detailUrlTemplate);
            })
            .catch(function(err) {
                console.error('Wikidata search error:', err);
                resultsContainer.innerHTML = '<div class="wikidata-error">Search failed. Try again.</div>';
                resultsContainer.style.display = 'block';
            });
    }

    function renderResults(results, container, selectedContainer, detailUrlTemplate) {
        container.innerHTML = '';

        if (results.length === 0) {
            container.innerHTML = '<div class="wikidata-no-results">No results found</div>';
            container.style.display = 'block';
            return;
        }

        results.forEach(function(item) {
            var div = document.createElement('div');
            div.className = 'wikidata-result-item';
            div.innerHTML =
                '<strong>' + escapeHtml(item.label) + '</strong>' +
                ' <span class="wikidata-qid">' + escapeHtml(item.qid) + '</span>' +
                (item.description ? '<br><small>' + escapeHtml(item.description) + '</small>' : '');

            div.addEventListener('click', function() {
                selectEntity(item, container, selectedContainer, detailUrlTemplate);
            });

            container.appendChild(div);
        });

        container.style.display = 'block';
    }

    function selectEntity(item, resultsContainer, selectedContainer, detailUrlTemplate) {
        resultsContainer.style.display = 'none';

        // Show loading state
        selectedContainer.innerHTML =
            '<div class="wikidata-selected-item">Loading details for ' +
            escapeHtml(item.qid) + '...</div>';
        selectedContainer.style.display = 'block';

        // Build detail URL from template
        var detailUrl = detailUrlTemplate.replace('__QID__', item.qid);

        // Fetch full entity details
        fetch(detailUrl)
            .then(function(response) { return response.json(); })
            .then(function(detail) {
                populateFields(item, detail);
                showSelected(item, detail, selectedContainer);
            })
            .catch(function(err) {
                console.error('Wikidata detail fetch error:', err);
                // Still populate with what we have from search
                populateFields(item, null);
                showSelected(item, null, selectedContainer);
            });
    }

    function populateFields(item, detail) {
        // Populate wikidata_id
        var wikidataIdField = document.getElementById('id_wikidata_id');
        if (wikidataIdField) {
            wikidataIdField.value = item.qid;
        }

        // Populate name from label
        var nameField = document.getElementById('id_name');
        if (nameField && !nameField.readOnly) {
            nameField.value = item.label;
        }

        // Generate key from label (snake_case)
        var keyField = document.getElementById('id_key');
        if (keyField && !keyField.readOnly) {
            keyField.value = toSnakeCase(item.label);
        }

        // Populate description
        var descField = document.getElementById('id_description');
        if (descField) {
            var desc = item.description || '';
            if (desc) {
                // Capitalize first letter
                desc = desc.charAt(0).toUpperCase() + desc.slice(1);
                // Add period if missing
                if (desc && !desc.endsWith('.')) {
                    desc += '.';
                }
            }
            descField.value = desc;
        }

        // Populate examples from aliases
        var examplesField = document.getElementById('id_examples');
        if (examplesField && detail && detail.aliases && detail.aliases.length > 0) {
            examplesField.value = detail.aliases.slice(0, 5).join(', ');
        }

        // Clear the search input
        var searchInput = document.getElementById('wikidata-search-input');
        if (searchInput) {
            searchInput.value = '';
        }
    }

    function showSelected(item, detail, container) {
        var aliases = (detail && detail.aliases) ? detail.aliases.slice(0, 5).join(', ') : '';
        container.innerHTML =
            '<div class="wikidata-selected-item">' +
            '<strong>' + escapeHtml(item.label) + '</strong> ' +
            '<span class="wikidata-qid">' + escapeHtml(item.qid) + '</span>' +
            (item.description ? '<br><small>' + escapeHtml(item.description) + '</small>' : '') +
            (aliases ? '<br><small>Aliases: ' + escapeHtml(aliases) + '</small>' : '') +
            '<br><small class="wikidata-autofill-note">Fields populated from Wikidata. Review and adjust as needed.</small>' +
            '</div>';
        container.style.display = 'block';
    }

    function toSnakeCase(str) {
        return str
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, '_')
            .replace(/^_+|_+$/g, '');
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(text));
        return div.innerHTML;
    }

    // Expose init for the template
    window.wikidataSearch = { init: init };
})();
