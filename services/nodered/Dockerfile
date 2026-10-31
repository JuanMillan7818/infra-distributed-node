# Node-RED + Dashboard 2.0 con el flujo del tablero de ventas ya cargado.
ARG NODE_RED_TAG=4.1
FROM nodered/node-red:${NODE_RED_TAG}

# Los módulos se instalan en el userDir de la imagen; /data (volumen) queda solo para el contexto persistente.
RUN npm install --no-audit --no-fund --omit=dev @flowfuse/node-red-dashboard@1

# Flujo y ajustes versionados en el repo: fuera de /data para que cada rebuild aplique la versión del repo.
COPY --chown=node-red:node-red settings.js flows.json /opt/nodered/

# entrypoint.sh de la imagen ejecuta: red.js --userDir /data $FLOWS <CMD>
ENV FLOWS=/opt/nodered/flows.json
CMD ["--settings", "/opt/nodered/settings.js"]
