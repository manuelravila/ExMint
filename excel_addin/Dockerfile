# Use an official Node.js runtime as a parent image
FROM node:18

# Set the working directory
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Upgrade npm to the latest version
RUN npm install -g npm@latest

# Upgrade @azure/msal-node package to the latest version
RUN npm install @azure/msal-node@latest

# Install dependencies, including devDependencies
RUN npm install

# Run npm audit fix to address vulnerabilities automatically
RUN npm audit fix || echo "Continuing build process even if npm audit fix fails"

# Install webpack and webpack-cli globally to ensure they are available in the PATH
RUN npm install -g webpack webpack-cli

# Build the application (this will generate the files in the dist folder)
RUN npm run build

# Serve the application from the dist directory
WORKDIR /app/dist

# Install http-server globally to serve the dist folder
RUN npm install -g http-server

# Expose the port the application will run on
EXPOSE 3000

# Start the application by serving the dist directory using http-server
CMD ["http-server", ".", "-p", "3000"]
