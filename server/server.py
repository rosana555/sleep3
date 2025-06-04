import paho.mqtt.client as mqtt

def on_message(client, userdata, msg):
    processed = msg.payload.decode().upper()
    print("Processed:", processed)
    client.publish("/output", processed)

client = mqtt.Client("server")
client.connect("broker", 1883)

client.subscribe("/input")
client.on_message = on_message
client.loop_forever()
