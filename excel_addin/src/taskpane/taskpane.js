import './taskpane.css';

function showToast(message) {
  const toast = document.createElement('div');
  toast.className = 'toaster';
  toast.textContent = message;

  document.body.appendChild(toast);
  setTimeout(() => document.body.removeChild(toast), 5000); // Change duration to 5 seconds
}


document.addEventListener('DOMContentLoaded', function () {
  const loginForm = document.querySelector('form');
  const serverAddress = window.appConfig.apiUrl;

  loginForm.addEventListener('submit', function (e) {
      e.preventDefault(); // Prevent the default form submission

      const formData = new FormData(loginForm);
      const data = {};
      formData.forEach((value, key) => { data[key] = value; });

      fetch(`${serverAddress}/login`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Request-Source': 'Excel-Add-In'
        },
        body: JSON.stringify(data)
      })
      .then(response => {
          if (!response.ok) { // Check if the response status is not in the 2xx range
              throw new Error('Login Unsuccessful. Please check email and password');
          }
          return response.json(); // Only parse as JSON if response is ok
      })
      .then(data => {
          localStorage.setItem('authToken', data.token);
          console.log('Login successful, token stored.');
          window.location.href = 'dashboard.html'; // Redirect on success
      })
      .catch((error) => {
        console.error('Error:', error);
        showToast('Login Unsuccessful. Please check email and password'); // Call with simple text
    });
    
  });
});


// Example function for fetching protected data, demonstrating how to use the server address and token
function fetchProtectedData() {
  const token = localStorage.getItem('authToken'); // Retrieve the stored token

  if (!token) {
      console.log('No token found, please log in first.');
      return;
  }

  fetch(`${serverAddress}/some-protected-route`, { // Use the serverAddress variable
      method: 'GET',
      headers: {
          'Authorization': `Bearer ${token}`, // Include the token in the request
          'Content-Type': 'application/json'
      }
  })
  .then(response => response.json())
  .then(data => {
      console.log('Protected data:', data);
  })
  .catch(error => {
      console.error('Error fetching protected data:', error);
  });
}

//Dynamically set login form links
document.addEventListener('DOMContentLoaded', function() {
  const apiUrl = window.appConfig.apiUrl; // Get the API URL from your config

  // Set the href for the reset password link
  document.getElementById('resetPasswordLink').setAttribute('href', `${apiUrl}reset_password`);

  // Set the href for the create account link
  document.getElementById('createAccountLink').setAttribute('href', `${apiUrl}register`);
});
