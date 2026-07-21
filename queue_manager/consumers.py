import json
from channels.generic.websocket import AsyncWebsocketConsumer

class QueueConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.group_name = 'queue_group'

        # Join queue group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        # Leave queue group
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    # Receive message from WebSocket (client to server)
    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message = data.get('message', '')
            await self.send(text_data=json.dumps({
                'type': 'ack',
                'message': f'Received: {message}'
            }))
        except Exception as e:
            pass

    # Receive message from queue_group
    async def queue_update(self, event):
        # Send message to WebSocket client
        await self.send(text_data=json.dumps({
            'action': event['action'],
            'patient': event.get('patient', None),
            'timestamp': event.get('timestamp', None)
        }))
