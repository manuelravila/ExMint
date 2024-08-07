console.log("Taskpane script loaded");

function showToast(message) {
  const toast = document.createElement('div');
  toast.className = 'toaster';
  toast.textContent = message;

  document.body.appendChild(toast);
  setTimeout(() => document.body.removeChild(toast), 5000); // Change duration to 5 seconds
}

// Ensure Office.js is fully loaded
Office.onReady(function (info) {
  if (info.host === Office.HostType.Excel) {
    console.log("Office.js is ready");

    // Wait for DOMContentLoaded
    document.addEventListener('DOMContentLoaded', function () {
      console.log("DOM fully loaded and parsed");

      // Ensure window.appConfig is loaded before proceeding
      if (typeof window.appConfig === 'undefined') {
        console.error('window.appConfig is not defined');
        return;
      }

      const serverAddress = window.appConfig.backEndUrl;
      console.log('Server Address:', serverAddress);

      const loginForm = document.querySelector('form');
      if (loginForm) {
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
      } else {
        console.error('Login form not found.');
      }

      // Dynamically set login form links
      var resetPasswordLink = document.getElementById('resetPasswordLink');
      if (resetPasswordLink) {
        resetPasswordLink.addEventListener('click', function (event) {
          event.preventDefault(); // Prevent the default link behavior
          var url = 'https://exmint.me/app' + window.appConfig.suffix + '/password-reset';
          console.log('Link clicked:', url);
          window.open(url, '_blank'); // Open the URL in a new window/tab
        });
      } else {
        console.error('Reset password link not found.');
      }

      var createAccountLink = document.getElementById('createAccountLink');
      if (createAccountLink) {
        createAccountLink.addEventListener('click', function (event) {
          event.preventDefault(); // Prevent the default link behavior
          var url = 'https://exmint.me/app' + window.appConfig.suffix + '/register';
          console.log('Link clicked:', url);
          window.open(url, '_blank'); // Open the URL in a new window/tab
        });
      } else {
        console.error('Create account link not found.');
      }
    });
  } else {
    console.error("This add-in is not running in Excel.");
  }
});
