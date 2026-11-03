#pragma once
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <math.h>
#include <ctype.h>
#include <deque>
#include <string>
typedef uint8_t byte;
typedef bool boolean;
typedef std::string String;
#define A1 15
#define A2 16
#define LOW 0
#define HIGH 1
#define OUTPUT 1
#define INPUT 0
#define F(value) value
extern uint32_t fakeMillis;
extern int fakePins[24];
inline uint32_t millis(){return fakeMillis;}
inline void pinMode(int,int){}
inline int digitalRead(int pin){return fakePins[pin];}
inline void digitalWrite(int pin,int value){fakePins[pin]=value;}
inline void analogWrite(int pin,int value){fakePins[pin]=value;}
inline char* dtostrf(double value,signed char width,unsigned char precision,char* out){snprintf(out,10,"%*.*f",width,precision,value);return out;}
struct FakeSerial {
  std::deque<char> input;
  std::string output;
  int capacity=64;
  void begin(int){}
  int available(){return input.size();}
  int read(){char c=input.front();input.pop_front();return c;}
  int availableForWrite(){return capacity;}
  size_t write(const uint8_t* bytes,size_t n){output.append((const char*)bytes,n);return n;}
  void println(const char* s){output+=s;output+='\n';}
  void print(const char* s){output+=s;}
  void receive(const std::string& text){for(char c:text)input.push_back(c);}
};
extern FakeSerial Serial;
