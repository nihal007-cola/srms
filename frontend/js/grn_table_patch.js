// ==============================================================
// GRN TABLE - RENDER, SORT, FILTER
// ==============================================================

// Store GRN data for filtering/sorting
let grnDataCache = [];
let grnSortField = null;
let grnSortDirection = 'asc';

// Override renderGRNOrders - render as table with sticky header
function renderGRNOrders(orders) {
    const tb = document.getElementById('grnBody');
    if (!orders || orders.length === 0) {
        tb.innerHTML = `<tr><td colspan="11" style="text-align:center;color:var(--text-muted);padding:16px;">No GRN orders found.</td></tr>`;
        grnDataCache = [];
        return;
    }
    
    // Store data for filtering/sorting
    grnDataCache = orders.map(order => {
        const ordered = order.totalOrdered || 0;
        const received = order.totalReceived || 0;
        const balance = ordered - received;
        const status = order.status || 'PROCESSED';
        
        // Determine row class based on status and balance
        let rowClass = '';
        if (status === 'CANCELLED') rowClass = 'cancelled';
        else if (status === 'COMPLETED') rowClass = 'completed';
        else if (balance > 0 && status !== 'COMPLETED') rowClass = 'partial';
        else rowClass = 'pending';
        
        return {
            ...order,
            orderedQty: ordered,
            receivedQty: received,
            balanceQty: balance > 0 ? balance : 0,
            rowClass: rowClass,
            statusDisplay: status,
            fgKeys: order.fgKeys ? order.fgKeys.join(', ') : 'N/A',
            itemCount: order.items ? order.items.length : 0,
            orderDate: order.orderDate || '',
            lastUpdated: order.lastUpdated || order.orderDate || ''
        };
    });
    
    renderGRNTable(grnDataCache);
}

function renderGRNTable(data) {
    const tb = document.getElementById('grnBody');
    
    if (!data || data.length === 0) {
        tb.innerHTML = `<tr><td colspan="11" style="text-align:center;color:var(--text-muted);padding:16px;">No matching GRN orders found.</td></tr>`;
        return;
    }
    
    // Sort pending first, then apply user sort within groups
    let pending = data.filter(d => d.rowClass === 'pending' || d.rowClass === 'partial');
    let completed = data.filter(d => d.rowClass === 'completed' || d.rowClass === 'cancelled');
    
    // Apply sorting to each group
    if (grnSortField) {
        pending = sortData(pending, grnSortField, grnSortDirection);
        completed = sortData(completed, grnSortField, grnSortDirection);
    }
    
    const sortedData = [...pending, ...completed];
    
    let html = '';
    sortedData.forEach((order, index) => {
        const statusBadge = order.statusDisplay === 'PARTIAL' ? 'partial' : 
                           (order.statusDisplay === 'COMPLETED' ? 'completed' : 
                           (order.statusDisplay === 'CANCELLED' ? 'cancelled' : 'processed'));
        
        const balance = order.balanceQty || 0;
        const isPending = balance > 0 || order.statusDisplay !== 'COMPLETED';
        
        html += `<tr class="${order.rowClass}" data-index="${index}">
            <td class="sticky-col">
                <button class="btn btn-success btn-sm btn-receive" onclick="openGRNModal('${order.poToken}')">
                    <i class="fas fa-clipboard-check"></i> Receive
                </button>
            </td>
            <td><strong>${order.poToken || '—'}</strong></td>
            <td>${order.supplierAlias || order.supplier || ''}</td>
            <td class="fg-keys-cell" title="${order.fgKeys}">${order.fgKeys}</td>
            <td>${order.itemCount}</td>
            <td>${order.orderedQty.toFixed(2)}</td>
            <td>${order.receivedQty.toFixed(2)}</td>
            <td>${balance.toFixed(2)}</td>
            <td><span class="status-badge ${statusBadge}">${order.statusDisplay}</span></td>
            <td>${order.orderDate ? new Date(order.orderDate).toLocaleDateString('en-IN') : '—'}</td>
            <td>${order.lastUpdated ? new Date(order.lastUpdated).toLocaleDateString('en-IN') : '—'}</td>
        </tr>`;
    });
    
    tb.innerHTML = html;
}

function sortData(data, field, direction) {
    const multiplier = direction === 'asc' ? 1 : -1;
    return [...data].sort((a, b) => {
        let valA = a[field] ?? '';
        let valB = b[field] ?? '';
        
        // Handle numeric values
        if (typeof valA === 'number' && typeof valB === 'number') {
            return (valA - valB) * multiplier;
        }
        
        // Handle dates
        if (field === 'orderDate' || field === 'lastUpdated') {
            const dateA = valA ? new Date(valA) : new Date(0);
            const dateB = valB ? new Date(valB) : new Date(0);
            return (dateA - dateB) * multiplier;
        }
        
        // Handle strings
        valA = String(valA).toLowerCase();
        valB = String(valB).toLowerCase();
        if (valA < valB) return -1 * multiplier;
        if (valA > valB) return 1 * multiplier;
        return 0;
    });
}

function sortGRNTable(field) {
    if (grnSortField === field) {
        grnSortDirection = grnSortDirection === 'asc' ? 'desc' : 'asc';
    } else {
        grnSortField = field;
        grnSortDirection = 'asc';
    }
    
    // Update header icons
    document.querySelectorAll('#grnTable thead th[data-sort]').forEach(th => {
        th.classList.remove('sorted-asc', 'sorted-desc');
        const icon = th.querySelector('i');
        if (icon) icon.className = 'fas fa-sort';
    });
    
    const header = document.querySelector(`#grnTable thead th[data-sort="${field}"]`);
    if (header) {
        header.classList.add(grnSortDirection === 'asc' ? 'sorted-asc' : 'sorted-desc');
        const icon = header.querySelector('i');
        if (icon) icon.className = grnSortDirection === 'asc' ? 'fas fa-sort-up' : 'fas fa-sort-down';
    }
    
    // Re-render with sorting
    if (grnDataCache.length > 0) {
        const filtered = getFilteredData();
        renderGRNTable(filtered);
    }
}

function getFilteredData() {
    let data = [...grnDataCache];
    const filterInputs = document.querySelectorAll('#grnTable .filter-row .filter-input');
    
    filterInputs.forEach(input => {
        const col = input.dataset.col;
        const value = input.value.trim().toLowerCase();
        if (!value) return;
        
        if (col === 'status') {
            data = data.filter(d => d.statusDisplay === value.toUpperCase());
        } else if (col === 'poToken' || col === 'supplier' || col === 'fgKeys') {
            data = data.filter(d => String(d[col] || '').toLowerCase().includes(value));
        } else if (col === 'items' || col === 'orderedQty' || col === 'receivedQty' || col === 'balanceQty') {
            const numVal = parseFloat(value);
            if (!isNaN(numVal)) {
                data = data.filter(d => (d[col] || 0) >= numVal);
            }
        } else if (col === 'orderDate' || col === 'lastUpdated') {
            const dateVal = new Date(value);
            if (!isNaN(dateVal)) {
                const dateStr = value;
                data = data.filter(d => {
                    const dDate = d[col] ? new Date(d[col]) : null;
                    return dDate && dDate.toISOString().split('T')[0] === dateStr;
                });
            }
        }
    });
    
    return data;
}

function filterGRNTable() {
    if (grnDataCache.length === 0) return;
    const filtered = getFilteredData();
    
    // Apply sorting if any
    if (grnSortField) {
        const sorted = sortData(filtered, grnSortField, grnSortDirection);
        renderGRNTable(sorted);
    } else {
        renderGRNTable(filtered);
    }
}

// Keep the existing refreshGRNOrders function but override render
// We already overrode renderGRNOrders above

