
// ==============================================================
// AUTHENTICATION CHECK
// ==============================================================
// Check if user is logged in
const token = localStorage.getItem('access_token');
if (!token) {
    window.location.href = '/login';
}

// Verify token with server
fetch('/api/auth/me', {
    headers: {
        'Authorization': 'Bearer ' + token
    }
}).then(response => {
    if (!response.ok) {
        localStorage.removeItem('access_token');
        localStorage.removeItem('user');
        window.location.href = '/login';
    }
}).catch(() => {
    window.location.href = '/login';
});
