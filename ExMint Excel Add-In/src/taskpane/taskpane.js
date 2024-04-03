/* global console, document, Excel, Office, fetch, localStorage */

// Set the base URL based on the environment
let baseURL;
switch (process.env.FLASK_ENV) {
    case 'dev':
        baseURL = 'http://127.0.0.1:5000';
        break;
    case 'stag':
        baseURL = 'https://stg-app.exmint.me';
        break;
    default:
        baseURL = 'https://app.exmint.me';
}

Office.onReady((info) => {
    if (info.host === Office.HostType.Excel) {
        document.getElementById("sideload-msg").style.display = "none";
        document.getElementById("app-body").style.display = "flex";
        document.getElementById("run").onclick = run;

        // Event listener for login form submission
        document.getElementById('login-form').addEventListener('submit', handleLoginFormSubmit);

        // Event listener for register link click
        document.getElementById('register-link').addEventListener('click', function () {
            // Redirect to the registration form or show the registration form
            // Implement the registration form functionality separately
        });
    }
});

// Function to handle login form submission
function handleLoginFormSubmit(event) {
    event.preventDefault();
    const loginInput = document.getElementById('login-input').value;
    const passwordInput = document.getElementById('password-input').value;
    // Make API call to login endpoint
    fetch(`${baseURL}/login`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            login: loginInput,
            password: passwordInput,
        }),
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Store the authentication token in localStorage or sessionStorage
                localStorage.setItem('authToken', data.token);
                // Redirect to the dashboard or load the dashboard content
                loadDashboard();
            } else {
                // Show error message
                alert(data.message);
            }
        })
        .catch(error => {
            console.error('Error logging in:', error);
            // Show error message
            alert('Failed to login. Please try again.');
        });
}

// Function to load the dashboard content
function loadDashboard() {
    // Hide the login form and show the dashboard content
    document.getElementById('login-container').style.display = 'none';
    document.getElementById('dashboard-app').style.display = 'block';
    // Fetch connected banks and accounts
    fetchConnectedBanks();
    fetchAccounts();
}

export async function run() {
    try {
        await Excel.run(async (context) => {
            /*
             * Insert your Excel code here
             */
            const range = context.workbook.getSelectedRange();
            // Read the range address
            range.load("address");
            // Update the fill color
            range.format.fill.color = "yellow";
            await context.sync();
            console.log(`The range address was ${range.address}.`);
        });
    } catch (error) {
        console.error(error);
    }
}