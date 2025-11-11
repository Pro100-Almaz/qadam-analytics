import logging

logger = logging.getLogger('')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename="script_logging.log")
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)



