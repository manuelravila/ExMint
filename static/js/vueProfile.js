// vueProfile.js
function showToast(message, type = 'success') {
    var container = document.getElementById('toast-container');
    var toast = document.createElement('div');
    toast.textContent = message;
    toast.style.color = 'white';
    toast.style.padding = '10px';
    toast.style.borderRadius = '5px';
    toast.style.textAlign = 'center';
    toast.style.marginTop = '10px';
    toast.style.backgroundColor = type === 'success' ? 'green' : 'red';

    container.appendChild(toast);
    setTimeout(() => container.removeChild(toast), 3000);
}


var app = new Vue({
    el: '#profileModal',
    data: {
        email: '',
        password: '',
        passwordConfirmation: '',
        token: ''
    },
    methods: {
        submitForm: function() {
            var csrfToken = document.getElementById('csrf_token').value; // Retrieve CSRF token

            var payload = {
                email: this.email
            };

            // Add password to the payload only if it's filled out
            if (this.password && this.password === this.passwordConfirmation) {
                payload.password = this.password;
            }
        
            fetch('/profile', {
                method: 'POST',
                body: JSON.stringify(payload),
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                }
            })
            .then(response => {
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(data => {
                showToast('Profile updated successfully!','success');
            })
            .catch(error => {
                console.error('Error:', error);
                showToast('An error occurred. Please try again.', 'error');
            });
        },
        renewToken: async function() {
            try {
                const response = await fetch('/user-info', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ renew_token: true })
                });
        
                if (!response.ok) {
                    throw new Error(`Server responded with status: ${response.status}`);
                }
        
                const data = await response.json();
                //console.log("Response data:", data); // Debugging line
        
                if (data.token) {
                    this.token = data.token;
                    showToast('Token renewed successfully!', 'success');
                } else {
                    throw new Error('Server response did not include a token');
                }
            } catch (error) {
                showToast('An error occurred while renewing the token', 'error'); 
            }
        },
        
        fetchUserInfo: function() {
            //console.log("Fetching user info...");  // Log before fetching
            fetch('/user-info')
                .then(response => {
                    if (!response.ok) {
                        throw new Error('Network response was not ok');
                    }
                    return response.json();
                })
                .then(data => {
                    console.log("User info received:", data);  // Log received data
                    this.email = data.email;
                    this.token = data.token;  // Adjust to use token_info
                    // Example: Accessing a specific field in token payload
                    // this.user_id = data.token_info.user_id;
                })
                .catch(error => {
                    console.error('Error fetching user info:', error);  // Log any errors
                });
        }
       
    },
    mounted: function() {
        console.log("Vue instance mounted.");  // Log when Vue instance is mounted
        this.fetchUserInfo();
    },
});