FROM python:alpine3.7 
COPY /app /app
WORKDIR /app
RUN pip install -r requirements.txt 
EXPOSE 5001 
ENTRYPOINT [ "python" ] 
CMD [ "portable.py" ] 