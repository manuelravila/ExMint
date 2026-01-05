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
        passwordConfirmation: ''
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
