FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --legacy-peer-deps

COPY . .

RUN npm run build -- --configuration production

FROM nginx:stable-alpine
COPY --from=build /app/dist/simple-task-app /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
