#-------------------------------------------------
#
# Project created by QtCreator 2016-05-10T15:29:34
#
#-------------------------------------------------

QT       += core network websockets

QT       -= gui

TARGET = SampleApplication
CONFIG   += console
CONFIG   -= app_bundle

TEMPLATE = app


SOURCES += main.cpp \
           websocketclient.cpp \
           msgfactory.cpp \
           vantacommunicator.cpp

HEADERS += \
           websocketclient.h \
           vantacommunicator.h \
    msgfactory.h
