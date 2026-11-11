from src.services import baseline as service
def list_items():return service.list_baselines()
def create(data):return service.create(data)
