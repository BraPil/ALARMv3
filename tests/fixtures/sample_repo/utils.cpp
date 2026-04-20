#include "utils.h"
#include <iostream>

Helper::Helper() : name_("default") {}

void Helper::run() {
    std::cout << "Running: " << name_ << std::endl;
}

std::string Helper::getName() const {
    return name_;
}
