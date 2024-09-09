# Use an official Node.js runtime as a parent image
FROM node:18

# Set the working directory
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install dependencies, including devDependencies
RUN npm install

# Install webpack and webpack-cli globally to ensure they are available in the PATH
RUN npm install -g webpack webpack-cli

# Build the application (this will generate the files in the dist folder)
RUN npm run build

# Serve the application from the dist directory
WORKDIR /app/dist

# Use a simple static file server like 'serve'
RUN npm install -g serve

# Start the application by serving the dist directory
CMD ["serve", "-s", ".", "--single"]
