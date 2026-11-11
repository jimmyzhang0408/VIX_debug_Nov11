#ifndef CMDFACTORY_H
#define CMDFACTORY_H
#include <iostream>
#include <string>
#include <QJsonObject>
#include <QJsonDocument>

/* MessageFactory is a typical Factory class that creates various messages that can then be sent over a websocket interface
 * to a Vanta.
 */
class MessageFactory
{
public:
    enum VantaMessages
    {
        Login = 301,
        StartTest = 601,
        Notification = 403
    };

    enum VantaNotifications
    {
        SystemStatus = 100
    };

    MessageFactory();
    ~MessageFactory();

    /* Creates a Login message based upon the login and password provided.
     * All messages to the Vanta and responses received from the Vanta are JSON objects.
     * An example of the Create Login Message is shown below
     *       {
     *          "commandId": 301,
     *          "id": 1,
     *          "params": {
     *              "password": "0000",
     *              "userId": "Administrator"
     *          }
     *       }
     */
    std::string CreateLoginMessage(std::string login, std::string password);

    /* Creates a start test message.
     * An example of the Start Test Message is shown below.
     *       {
     *           "commandId": 601,
     *           "id": 1,
     *           "params": {
     *                     }
     *       }
     */
    std::string CreateStartTestMessage();

    /* A simple utility that will parse a response provided by a Vanta into relavant pieces.
     * An example of a login response from the device is shown below.
     *       {
     *           "commandId": 601,
     *           "id": 1,
     *           "params": {
     *                     }
     *       }
     */
    void parseMessageResponse(std::string respStr, int *msgId, int *id, std::string *error, std::string *params);

    /* A simple utility to parse the notification response from Vanta. */
    void parseSystemStatusNotification(std::string ssNotification, std::string *systemStatus, std::string *info);
};

#endif // CMDFACTORY_H

