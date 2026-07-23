// Enhanced filterTable function - works with table rows and cards
function filterTable(searchInputId, containerId, rowSelector = 'tr') {
    const input = document.getElementById(searchInputId);
    if (!input) return;
    const filter = input.value.toLowerCase();
    const container = document.getElementById(containerId);
    if (!container) return;

    // If container is a table body, filter its rows
    if (container.tagName === 'TBODY') {
        const rows = container.querySelectorAll('tr');
        rows.forEach(row => {
            const text = row.textContent.toLowerCase();
            row.style.display = text.includes(filter) ? '' : 'none';
        });
        return;
    }

    // Otherwise, handle cards or other elements
    const rows = container.querySelectorAll(rowSelector);
    if (rows.length === 0 && container.children.length > 0) {
        const cards = container.querySelectorAll('.po-card');
        cards.forEach(card => {
            const text = card.textContent.toLowerCase();
            card.style.display = text.includes(filter) ? '' : 'none';
        });
        return;
    }

    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(filter) ? '' : 'none';
    });
}
