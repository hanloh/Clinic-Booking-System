from flask import Flask, request, jsonify
from flask_cors import CORS

import os, sys

import requests
from invokes import invoke_http

import amqp_setup
import pika
import json

app = Flask(__name__)
CORS(app)

appointmentrecord_URL = f"http://127.0.0.1:5000/appointment/<string:clinicName>"
notification_URL = "http://127.0.0.1:5000/notification"


@app.route("/book_appointment", methods=['POST'])
def book_appointment():
    # Simple check of input format and data of the request are JSON
    if request.is_json:
        try:
            appointment = request.get_json()
            print("\nReceived an appointment record in JSON:", appointment)

            # do the actual work
            # 1. Send order info {cart items}
            
            result = processBookAppointment(appointment)
            print('\n------------------------')
            print('\nresult: ', result)
            return jsonify(result), result["code"]

        except Exception as e:
            # Unexpected error in code
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            ex_str = str(e) + " at " + str(exc_type) + ": " + fname + ": line " + str(exc_tb.tb_lineno)
            print(ex_str)

            return jsonify({
                "code": 500,
                "message": "book_appointment.py internal error: " + ex_str
            }), 500

    # if reached here, not a JSON request.
    return jsonify({
        "code": 400,
        "message": "Invalid JSON input: " + str(request.get_data())
    }), 400


def processBookAppointment(appointment):
    # 2. Send the order info {cart items}
    # Invoke the order microservice
    print('\n-----Invoking order microservice-----')
    clinicName = appointment["clinicName"]
    appointmentrecord_URL = f"http://127.0.0.1:5000/appointment/{clinicName}"
    appointment_result = invoke_http(appointmentrecord_URL, method='POST', json=appointment)
    print('appointment_result:', appointment_result)
  

    # Check the order result; if a failure, send it to the error microservice.
    code = appointment_result["code"]
    message = json.dumps(appointment_result)

    if code not in range(200, 300):
        # Inform the error microservice
        #print('\n\n-----Invoking error microservice as order fails-----')
        print('\n\n-----Publishing the (appointment error) message with routing_key=booking.error-----')

        # invoke_http(error_URL, method="POST", json=order_result)
        amqp_setup.channel.basic_publish(exchange=amqp_setup.exchangename, routing_key="booking.error", 
            body=message, properties=pika.BasicProperties(delivery_mode = 2)) 
        # make message persistent within the matching queues until it is received by some receiver 
        # (the matching queues have to exist and be durable and bound to the exchange)

        # - reply from the invocation is not used;
        # continue even if this invocation fails        
        print("\nAppointment status ({:d}) published to the RabbitMQ Exchange:".format(
            code), appointment_result)

        # 7. Return error
        return {
            "code": 500,
            "data": {"appointment_result": appointment_result},
            "message": "Appointment creation failure sent for error handling."
        }

    # Notice that we are publishing to "Activity Log" only when there is no error in order creation.
    # In http version, we first invoked "Activity Log" and then checked for error.
    # Since the "Activity Log" binds to the queue using '#' => any routing_key would be matched 
    # and a message sent to “Error” queue can be received by “Activity Log” too.

    else:
        # 4. Record new appointment
        # record the activity log anyway
        #print('\n\n-----Invoking activity_log microservice-----')
        print('\n\n-----Publishing the (appointment info) message with routing_key=appointment.info-----')        

        # invoke_http(activity_log_URL, method="POST", json=order_result)            
        amqp_setup.channel.basic_publish(exchange=amqp_setup.exchangename, routing_key="appointment.info", 
            body=message)
    
    print("\nAppointment published to RabbitMQ Exchange.\n")
    # - reply from the invocation is not used;
    # continue even if this invocation fails
    
    # # 5. Send new order to shipping
    # # Invoke the shipping record microservice
    # print('\n\n-----Invoking shipping_record microservice-----')    
    
    # shipping_result = invoke_http(
    #     shipping_record_URL, method="POST", json=order_result['data'])
    # print("shipping_result:", shipping_result, '\n')

    return {
        "code": 201,
        "data": {
            "appointment_result": appointment_result,
        }
    }


# Execute this program if it is run as a main script (not by 'import')
if __name__ == "__main__":
    print("This is flask " + os.path.basename(__file__) + " for placing an order...")
    app.run(host="0.0.0.0", port=5100, debug=True)
    # Notes for the parameters: 
    # - debug=True will reload the program automatically if a change is detected;
    #   -- it in fact starts two instances of the same flask program, and uses one of the instances to monitor the program changes;
    # - host="0.0.0.0" allows the flask program to accept requests sent from any IP/host (in addition to localhost),
    #   -- i.e., it gives permissions to hosts with any IP to access the flask program,
    #   -- as long as the hosts can already reach the machine running the flask program along the network;
    #   -- it doesn't mean to use http://0.0.0.0 to access the flask program.
