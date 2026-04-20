#pragma once
#include <string>

class Helper {
public:
    Helper();
    void run();
    std::string getName() const;
private:
    std::string name_;
};
