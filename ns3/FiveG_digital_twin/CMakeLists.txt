# FiveG_digital_twin uses nlohmann/json (single-header, no link required).
# The previous CMakeLists linked jsoncpp by mistake; it is removed now.

add_executable(FiveG_digital_twin
   FiveG_digital_twin.cc
   metrics-calc.cc
   debug-functions.cc
)

target_link_libraries(FiveG_digital_twin PRIVATE ${ns3-libs} ${ns3-contrib-libs})

target_compile_features(FiveG_digital_twin PRIVATE cxx_std_20)
target_compile_options(FiveG_digital_twin PRIVATE -Wall -Wextra -Wpedantic -Wno-unused-parameter)
