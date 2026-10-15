# C-01: imagen de desarrollo (dev server Vite). Imagen prod en C-11.
FROM node:24-alpine

WORKDIR /srv/web

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]
