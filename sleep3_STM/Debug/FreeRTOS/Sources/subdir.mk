################################################################################
# Automatically-generated file. Do not edit!
# Toolchain: GNU Tools for STM32 (13.3.rel1)
################################################################################

# Add inputs and outputs from these tool invocations to the build variables 
C_SRCS += \
../FreeRTOS/Sources/croutine.c \
../FreeRTOS/Sources/event_groups.c \
../FreeRTOS/Sources/list.c \
../FreeRTOS/Sources/queue.c \
../FreeRTOS/Sources/stream_buffer.c \
../FreeRTOS/Sources/tasks.c \
../FreeRTOS/Sources/timers.c 

OBJS += \
./FreeRTOS/Sources/croutine.o \
./FreeRTOS/Sources/event_groups.o \
./FreeRTOS/Sources/list.o \
./FreeRTOS/Sources/queue.o \
./FreeRTOS/Sources/stream_buffer.o \
./FreeRTOS/Sources/tasks.o \
./FreeRTOS/Sources/timers.o 

C_DEPS += \
./FreeRTOS/Sources/croutine.d \
./FreeRTOS/Sources/event_groups.d \
./FreeRTOS/Sources/list.d \
./FreeRTOS/Sources/queue.d \
./FreeRTOS/Sources/stream_buffer.d \
./FreeRTOS/Sources/tasks.d \
./FreeRTOS/Sources/timers.d 


# Each subdirectory must supply rules for building sources it contributes
FreeRTOS/Sources/%.o FreeRTOS/Sources/%.su FreeRTOS/Sources/%.cyclo: ../FreeRTOS/Sources/%.c FreeRTOS/Sources/subdir.mk
	arm-none-eabi-gcc "$<" -mcpu=cortex-m4 -std=gnu11 -g3 -DDEBUG -DUSE_HAL_DRIVER -DSTM32F411xE -c -I../Core/Inc -I../Drivers/STM32F4xx_HAL_Driver/Inc -I../Drivers/STM32F4xx_HAL_Driver/Inc/Legacy -I../Drivers/CMSIS/Device/ST/STM32F4xx/Include -I../Drivers/CMSIS/Include -I"C:/Users/kamen/Documents/DOCUMENTS/School/Projekt/sleep3/sleep3_STM/FreeRTOS/Sources/include" -I"C:/Users/kamen/Documents/DOCUMENTS/School/Projekt/sleep3/sleep3_STM/FreeRTOS/Sources/portable/GCC/ARM_CM4F" -I"C:/Users/kamen/Documents/DOCUMENTS/School/Projekt/sleep3/sleep3_STM/FreeRTOS/Sources/portable/MemMang" -O0 -ffunction-sections -fdata-sections -Wall -fstack-usage -fcyclomatic-complexity -MMD -MP -MF"$(@:%.o=%.d)" -MT"$@" --specs=nano.specs -mfpu=fpv4-sp-d16 -mfloat-abi=hard -mthumb -o "$@"

clean: clean-FreeRTOS-2f-Sources

clean-FreeRTOS-2f-Sources:
	-$(RM) ./FreeRTOS/Sources/croutine.cyclo ./FreeRTOS/Sources/croutine.d ./FreeRTOS/Sources/croutine.o ./FreeRTOS/Sources/croutine.su ./FreeRTOS/Sources/event_groups.cyclo ./FreeRTOS/Sources/event_groups.d ./FreeRTOS/Sources/event_groups.o ./FreeRTOS/Sources/event_groups.su ./FreeRTOS/Sources/list.cyclo ./FreeRTOS/Sources/list.d ./FreeRTOS/Sources/list.o ./FreeRTOS/Sources/list.su ./FreeRTOS/Sources/queue.cyclo ./FreeRTOS/Sources/queue.d ./FreeRTOS/Sources/queue.o ./FreeRTOS/Sources/queue.su ./FreeRTOS/Sources/stream_buffer.cyclo ./FreeRTOS/Sources/stream_buffer.d ./FreeRTOS/Sources/stream_buffer.o ./FreeRTOS/Sources/stream_buffer.su ./FreeRTOS/Sources/tasks.cyclo ./FreeRTOS/Sources/tasks.d ./FreeRTOS/Sources/tasks.o ./FreeRTOS/Sources/tasks.su ./FreeRTOS/Sources/timers.cyclo ./FreeRTOS/Sources/timers.d ./FreeRTOS/Sources/timers.o ./FreeRTOS/Sources/timers.su

.PHONY: clean-FreeRTOS-2f-Sources

