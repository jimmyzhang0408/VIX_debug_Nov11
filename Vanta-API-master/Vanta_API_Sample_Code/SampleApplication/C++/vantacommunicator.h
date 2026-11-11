#ifndef VANTACOMMUNICATOR_H
#define VANTACOMMUNICATOR_H
#include <QCoreApplication>
#include "websocketclient.h"
#include "msgfactory.h"

/* A simple class that allows the application to open up a connection with a Vanta using the OTG interface.
 * When a healthy connection is established it allows the application to send various commands to the Vanta
 * and receive responses from it.
 */
class VantaCommunicator
{
public:
    VantaCommunicator();
    ~VantaCommunicator();

    /* This method will be called by the Websocket interface when it has received some response from a Vanta.
     */
    void messageResponse(std::string response);

    /* This method will be called by the websocket interface when it has successfully established a connection with a Vanta
     * and it is ready to accept commands or if an error happens on the interface.
     */
    void status(std::string status);

    /* This will initiate a Websocket connection with a Vanta device. */
    void start(QCoreApplication *app);

private:
    MessageFactory   m_vantaMessageFactory;
    WebSocketClient  m_vantaConnection;
};

#endif // VANTACOMMUNICATOR_H

