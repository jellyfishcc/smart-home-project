"""Compile the actual UNOI source against fake Arduino I/O; never upload."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUB = r"""
#pragma once
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <sstream>
#include <string>
using std::isnan;
#define HIGH 1
#define LOW 0
#define OUTPUT 1
#define INPUT 0
#define DHT11 11
#define NEO_GRB 1
#define NEO_KHZ800 2
#define U8G2_R0 0
#define F(x) x
const int u8g2_font_6x12_tr=0;
unsigned long ticks=0;
int pins[32]={};
void pinMode(int,int){}
void digitalWrite(int pin,int value){pins[pin]=value;}
int digitalRead(int pin){return pins[pin];}
unsigned long millis(){return ticks;}
void delay(unsigned long ms){ticks+=ms;}
struct FakeSerial {
 std::ostringstream log;
 void begin(int){} int available(){return 0;} int read(){return -1;}
 template<class T> void print(T v){log<<v;}
 void print(uint8_t v){log<<int(v);}
 template<class T> void println(T v){print(v);log<<'\n';}
 void println(){log<<'\n';}
} Serial;
struct U8G2_SH1106_128X64_NONAME_1_4W_HW_SPI {
 template<class... T> U8G2_SH1106_128X64_NONAME_1_4W_HW_SPI(T...){}
 void begin(){} void setContrast(int){} void clearBuffer(){} void setFont(int){}
 void drawStr(int,int,const char*){} void sendBuffer(){} void firstPage(){}
 void setCursor(int,int){} template<class T> void print(T){} bool nextPage(){return false;}
};
struct DHT {DHT(int,int){} void begin(){} float readHumidity(){return 25;} float readTemperature(){return 21.5;}};
struct Adafruit_NeoPixel {
 int brightness=0; bool lit=false;
 Adafruit_NeoPixel(int,int,int){} void begin(){} void setBrightness(int b){brightness=b;}
 void clear(){lit=false;} void show(){} int Color(int,int,int){return 1;}
 void setPixelColor(int,int){lit=true;}
};
void readDHT(); void readLight(); void controlFan(); void controlLamp(); void displayOLED();
"""
HARNESS = r"""
#include <cassert>
#include <iostream>
#include "UNOI_SOURCE"
int main(){
 setup();
 assert(!fanManual && !lampManual && pins[FAN_PIN]==HIGH && !strip.lit);
 temperature=21.5;
 handleCmd("FAN 1"); controlFan();
 assert(fanManual && fanState && pins[FAN_PIN]==LOW);
 handleCmd("FAN 0");
 for(float t: {21.5f, 29.0f, 35.0f}){temperature=t; for(int i=0;i<10;i++)controlFan(); assert(fanManual && !fanState && pins[FAN_PIN]==HIGH);}
 handleCmd("FAN AUTO"); assert(!fanManual && fanState);
 temperature=29;controlFan();assert(fanState);
 temperature=28;controlFan();assert(!fanState);
 temperature=29;controlFan();assert(!fanState);
 temperature=30;controlFan();assert(fanState);
 temperature=21.5;handleCmd("FAN AUTO");assert(!fanState && pins[FAN_PIN]==HIGH);
 darkState=true;handleCmd("LAMP 1 60");assert(lampManual && lampOn && strip.lit);
 handleCmd("LAMP 0");
 for(int i=0;i<30;i++){ticks+=1000;darkState=(i%2)==0;controlLamp();assert(lampManual && !lampOn && !strip.lit && strip.brightness==0);}
 darkState=true;handleCmd("LAMP AUTO");assert(!lampManual && lampOn && strip.lit);
 darkState=false;controlLamp();assert(!lampOn);
 darkState=true;controlLamp();assert(lampOn);
 auto log=Serial.log.str();
 assert(log.find("@ACK FAN AUTO")!=std::string::npos);
 assert(log.find("@EVT CTL MANUAL_OFF FAN")!=std::string::npos);
 assert(log.find("@EVT CTL MANUAL_OFF LAMP")!=std::string::npos);
 assert(log.find("@EVT FAN OFF")!=std::string::npos);
 assert(log.find("@EVT LAMP OFF 0")!=std::string::npos);
 assert(log.find("@BOOT 1 env-tristate-1")!=std::string::npos);
 // Repeated OFF still reports the actual output, so reconnecting clients can recover.
 Serial.log.str("");handleCmd("FAN 0");handleCmd("FAN 0");
 assert(Serial.log.str().find("@EVT FAN OFF")!=std::string::npos);
 std::cout<<"UNOI firmware state/IO/protocol assertions passed\n";
}
"""


def compile_run(source, program=HARNESS):
    compiler = shutil.which('g++')
    if not compiler:
        raise unittest.SkipTest('g++ unavailable; host firmware test not run')
    with tempfile.TemporaryDirectory(prefix='unoi-fake-io-') as temp:
        tmp = Path(temp)
        (tmp/'fake.h').write_text(STUB)
        for header in ('Arduino.h','U8g2lib.h','Wire.h','DHT.h','Adafruit_NeoPixel.h'):
            (tmp/header).write_text('#include "fake.h"\n')
        (tmp/'test.cpp').write_text(program.replace('UNOI_SOURCE',str(source)))
        subprocess.run([compiler,'-std=c++11','-I',str(tmp),str(tmp/'test.cpp'),'-o',str(tmp/'test')],check=True,capture_output=True,text=True)
        return subprocess.run([str(tmp/'test')],check=True,capture_output=True,text=True).stdout


class FirmwareModeTests(unittest.TestCase):
    def test_actual_unoi_state_machine_and_outputs(self):
        self.assertIn('assertions passed',compile_run(ROOT/'硬件代码/design-and-build-project-main/UNOI'))

    def test_unoi_sources_identical(self):
        folder=ROOT/'硬件代码/design-and-build-project-main'
        self.assertEqual((folder/'UNOI').read_bytes(),(folder/'UNOI.txt').read_bytes())
