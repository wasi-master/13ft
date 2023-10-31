FROM python:3.9.18-alpine
COPY /app /app
WORKDIR /app
RUN pip install -r requirements.txt 
EXPOSE 5001 
ENTRYPOINT [ "python" ] 
CMD [ "portable.py" ] 