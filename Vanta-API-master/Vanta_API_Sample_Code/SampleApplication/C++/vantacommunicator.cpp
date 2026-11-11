#include "vantacommunicator.h"

VantaCommunicator::VantaCommunicator()
{
}

VantaCommunicator::~VantaCommunicator()
{
}

void VantaCommunicator::messageResponse(std::string response)
{
    int messageId, id;
    std::string error, params, systemStatus, info;
    m_vantaMessageFactory.parseMessageResponse(response, &messageId, &id, &error, &params);

    switch(messageId) {
    case MessageFactory::Login: {
        std::cout << "Got a Login response back from Vanta. " << response << std::endl;
        std::string startTestMessage = m_vantaMessageFactory.CreateStartTestMessage();

        std::cout << "Sending a Start Test Message " << std::endl << startTestMessage << std::endl;
        std::cout << "Now starting a test... " << std::endl;
        m_vantaConnection.sendToVanta(startTestMessage);
        break;
    }

    case MessageFactory::StartTest:
        break;

    case MessageFactory::Notification:
        switch(id) {
            case MessageFactory::SystemStatus: {
                m_vantaMessageFactory.parseSystemStatusNotification(params, &systemStatus, &info);
                std::cout << "System status message " << systemStatus << std::endl;
                if (info.length() > 0)
                    std::cout << "System status info " << info << std::endl;
                break;
            }
            default: {
                break;
            }
        }
        break;

    default:
        // std::cout << "some response " << response << std::endl;
        break;
    }
}

void VantaCommunicator::status(std::string status)
{
    if (status.compare(std::string("ok"))==0) {

        std::cout << "Established a websocket connection with the Vanta." << std::endl;
        std::string loginMessage = m_vantaMessageFactory.CreateLoginMessage("Administrator","0000");

        std::cout << "Creating a Login message " << std::endl << loginMessage << std::endl;
        std::cout << "Logging in to a Vanta as Administrator... " << std::endl;
        m_vantaConnection.sendToVanta(loginMessage);

    } else {

        std::cout << "Websocket error " << status;
    }
}

void VantaCommunicator::start(QCoreApplication *app)
{
    /* Set the communicator instance with the WebSocket client so that the status() and messageResponse()
     * can be called to provide the health information of the connection and the response from Vanta.
     */
    m_vantaConnection.setVcInstance(this);

    /* Now connect to the device using the OTG interface. */
    std::string deviceIpAddr("192.168.7.2");

    std::cout << "Connecting to Vanta over the OTG interface " << deviceIpAddr << std::endl;
    m_vantaConnection.connectToVanta(deviceIpAddr);

    /* Execute the Qt application event loop. */
    app->exec();
}
